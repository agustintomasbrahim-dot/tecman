import copy
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


_TEST_ROOT = tempfile.TemporaryDirectory()
os.environ["TECMAN_DATA_DIR"] = str(Path(_TEST_ROOT.name) / "data")
os.environ["TECMAN_UPLOADS_DIR"] = str(Path(_TEST_ROOT.name) / "uploads")
os.environ.pop("DATABASE_URL", None)

import app as tecman  # noqa: E402


class CerrarMaterialesSinSalidaTest(unittest.TestCase):
    TICKET_ID = 100901

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.original_paths = (
            tecman.TICKETS_FILE,
            tecman.STOCK_FILE,
            tecman.STOCK_MOV_FILE,
            tecman.STOCK_LOTES_FILE,
            tecman.COMPROBANTES_FILE,
            tecman.UPLOADS_DIR,
        )
        tecman.TICKETS_FILE = root / "tickets.json"
        tecman.STOCK_FILE = root / "stock.json"
        tecman.STOCK_MOV_FILE = root / "stock_movimientos.json"
        tecman.STOCK_LOTES_FILE = root / "stock_lotes.json"
        tecman.COMPROBANTES_FILE = root / "comprobantes.json"
        tecman.UPLOADS_DIR = root / "uploads"
        tecman.UPLOADS_DIR.mkdir()
        tecman.USE_DB = False
        tecman.app.config.update(TESTING=True, SECRET_KEY="close-without-dispatch-test")
        tecman._atomic_write(tecman.TICKETS_FILE, [self._ticket()])
        tecman.save_stock({"central": {"Cable": {"cantidad": 12, "precio_unitario": 3}}, "sucursales": {}})
        tecman.save_movimientos({"movimientos": [{"id": "existing"}]})
        tecman.save_lotes_fifo({"lotes": [{"id": "existing-lot"}]})
        tecman.save_comprobantes({"comprobantes": [{"id": "existing-doc"}]})
        (tecman.UPLOADS_DIR / "adjunto-existente.pdf").write_bytes(b"fixture")
        self.client = tecman.app.test_client()
        self.admin_session()

    def tearDown(self):
        (
            tecman.TICKETS_FILE,
            tecman.STOCK_FILE,
            tecman.STOCK_MOV_FILE,
            tecman.STOCK_LOTES_FILE,
            tecman.COMPROBANTES_FILE,
            tecman.UPLOADS_DIR,
        ) = self.original_paths
        tecman.USE_DB = False
        self.temp.cleanup()

    def _ticket(self, **overrides):
        ticket = {
            "id": self.TICKET_ID,
            "sucursal": "Sucursal 142",
            "categoria": "Materiales",
            "subcategoria": "Solicitud de materiales",
            "tipo": "materiales",
            "descripcion": "Pedido repetido",
            "estado": "Nuevo",
            "creado": "2026-11-05T10:00:00",
            "actualizado": "2026-11-05T10:00:00",
            "adjuntos": [{"archivo": "adjunto-existente.pdf"}],
            "campo_legacy": {"conservar": True},
            "notas": [{"autor": "Sucursal 142", "fecha": "2026-11-05T10:00:00", "texto": "Original"}],
        }
        ticket.update(overrides)
        return ticket

    def admin_session(self):
        with self.client.session_transaction() as session:
            session.clear()
            session.update(user="admin-test", nombre="Administración Test", rol="admin", _csrf_token="csrf-test")

    def logistics_session(self):
        with self.client.session_transaction() as session:
            session.clear()
            session.update(
                user="dabra-test",
                nombre="Logística Dabra",
                rol="tecnico",
                auth_account_role=tecman.PREPARADOR_DABRA_ROLE,
                _csrf_token="csrf-test",
            )

    def entra_technician_session(self):
        with self.client.session_transaction() as session:
            session.clear()
            session.update(
                user="entra-tech-test",
                nombre="Técnico Entra",
                rol="tecnico",
                auth_provider="entra",
                entra_role="tecnico",
                _csrf_token="csrf-test",
            )

    def unauthorized_session(self):
        with self.client.session_transaction() as session:
            session.clear()
            session.update(user="tecnico-test", nombre="Técnico", rol="tecnico", _csrf_token="csrf-test")

    def branch_session(self):
        with self.client.session_transaction() as session:
            session.clear()
            session.update(suc_user="suc142", suc_nombre="Sucursal 142", _csrf_token="csrf-test")

    def _post(self, **overrides):
        payload = {
            "_csrf_token": "csrf-test",
            "motivo_tipo": "duplicado",
            "motivo": "Duplicado del ticket #100900; no corresponde despacho.",
            "idempotency_key": "close-100901-1",
        }
        payload.update(overrides)
        return self.client.post(
            f"/admin/pedido/{self.TICKET_ID}/cerrar-sin-salida", data=payload
        )

    def _runtime_snapshot(self):
        return {
            "tickets": tecman.TICKETS_FILE.read_bytes(),
            "stock": tecman.STOCK_FILE.read_bytes(),
            "movements": tecman.STOCK_MOV_FILE.read_bytes(),
            "lots": tecman.STOCK_LOTES_FILE.read_bytes(),
            "documents": tecman.COMPROBANTES_FILE.read_bytes(),
            "uploads": {p.name: p.read_bytes() for p in tecman.UPLOADS_DIR.iterdir()},
        }

    def test_admin_cierra_y_conserva_datos_sin_efectos_de_inventario(self):
        before = self._runtime_snapshot()
        original = copy.deepcopy(tecman._load_tickets_raw()[0])
        response = self._post()
        self.assertEqual(response.status_code, 302)

        saved = tecman._load_tickets_raw()[0]
        self.assertEqual(saved["estado"], "Cerrado")
        self.assertEqual(saved["adjuntos"], original["adjuntos"])
        self.assertEqual(saved["campo_legacy"], original["campo_legacy"])
        self.assertEqual(saved["cierre_sin_salida"]["actor"], "Administración Test")
        self.assertEqual(saved["cierre_sin_salida"]["motivo_tipo"], "duplicado")
        self.assertIn("Duplicado del ticket", saved["cierre_sin_salida"]["motivo"])
        self.assertTrue(saved["cierre_sin_salida"]["sin_descuento_stock"])
        self.assertEqual(saved["notas"][-1]["tipo"], "cierre_sin_salida")
        self.assertEqual(len(saved["cierre_sin_salida_historial"]), 1)
        after = self._runtime_snapshot()
        for key in ("stock", "movements", "lots", "documents", "uploads"):
            self.assertEqual(after[key], before[key])

    def test_accion_separada_es_visible_y_ejecutable_solo_por_administracion(self):
        page = self.client.get(f"/admin/pedido/{self.TICKET_ID}")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"Cerrar sin salida", page.data)
        self.assertIn(b"/cerrar-sin-salida", page.data)
        self.assertEqual(self._post(idempotency_key="admin-close").status_code, 302)
        self.assertEqual(
            tecman._load_tickets_raw()[0]["cierre_sin_salida"]["actor"],
            "Administración Test",
        )

    def test_logistica_sucursal_y_tecnicos_no_ven_y_no_pueden_ejecutar(self):
        self.logistics_session()
        page = self.client.get(f"/admin/pedido/{self.TICKET_ID}")
        self.assertEqual(page.status_code, 200)
        self.assertNotIn(b"Cerrar sin salida", page.data)
        baseline = self._runtime_snapshot()
        self.assertEqual(self._post(idempotency_key="logistica-close").status_code, 403)
        self.assertEqual(self._runtime_snapshot(), baseline)

        self.entra_technician_session()
        page = self.client.get(f"/admin/pedido/{self.TICKET_ID}")
        self.assertEqual(page.status_code, 200)
        self.assertNotIn(b"Cerrar sin salida", page.data)
        self.assertEqual(self._post(idempotency_key="entra-tech-close").status_code, 403)
        self.assertEqual(self._runtime_snapshot(), baseline)

        self.unauthorized_session()
        page = self.client.get(f"/admin/pedido/{self.TICKET_ID}")
        self.assertEqual(page.status_code, 200)
        self.assertNotIn(b"Cerrar sin salida", page.data)
        baseline = self._runtime_snapshot()
        self.assertEqual(self._post().status_code, 403)
        self.assertEqual(self._runtime_snapshot(), baseline)

        self.branch_session()
        self.assertEqual(self._post().status_code, 403)
        self.assertEqual(self._runtime_snapshot(), baseline)

    def test_csrf_motivo_estado_clase_e_idempotencia_sin_mutaciones_indebidas(self):
        invalid = [
            {"_csrf_token": ""},
            {"motivo_tipo": "inventado"},
            {"motivo": ""},
            {"motivo": "x" * (tecman.MATERIAL_CLOSE_WITHOUT_DISPATCH_MAX_LENGTH + 1)},
            {"idempotency_key": ""},
            {"idempotency_key": "clave con espacios"},
        ]
        baseline = self._runtime_snapshot()
        for payload in invalid:
            with self.subTest(payload=payload):
                self.assertEqual(self._post(**payload).status_code, 400)
                self.assertEqual(self._runtime_snapshot(), baseline)
        missing = self.client.post(
            "/admin/pedido/999999/cerrar-sin-salida",
            data={
                "_csrf_token": "csrf-test",
                "motivo_tipo": "duplicado",
                "motivo": "Duplicado inexistente",
                "idempotency_key": "missing-close",
            },
        )
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(self._runtime_snapshot(), baseline)

        tecman._atomic_write(tecman.TICKETS_FILE, [self._ticket(estado="Resuelto")])
        final_baseline = self._runtime_snapshot()
        self.assertEqual(self._post().status_code, 409)
        self.assertEqual(self._runtime_snapshot(), final_baseline)

        tecman._atomic_write(tecman.TICKETS_FILE, [self._ticket(categoria="Reparaciones", subcategoria="General", tipo="")])
        wrong_class_baseline = self._runtime_snapshot()
        self.assertEqual(self._post().status_code, 400)
        self.assertEqual(self._runtime_snapshot(), wrong_class_baseline)

        tecman._atomic_write(tecman.TICKETS_FILE, [self._ticket()])
        self.assertEqual(self._post().status_code, 302)
        once = self._runtime_snapshot()
        self.assertEqual(self._post().status_code, 302)
        self.assertEqual(self._runtime_snapshot(), once)

    def test_sucursal_cerrada_no_muestra_ni_admite_cierre_sin_salida(self):
        tecman._atomic_write(
            tecman.TICKETS_FILE,
            [self._ticket(sucursal="Sucursal 166", sucursal_num="166")],
        )
        baseline = self._runtime_snapshot()

        page = self.client.get(f"/admin/pedido/{self.TICKET_ID}")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"Sucursal cerrada", page.data)
        self.assertNotIn(b"Cerrar sin salida", page.data)

        response = self._post(idempotency_key="closed-branch-close")
        self.assertEqual(response.status_code, 409)
        self.assertIn(b"s\xc3\xb3lo para consulta", response.data)
        self.assertEqual(self._runtime_snapshot(), baseline)

    def test_backend_db_bloquea_y_actualiza_solo_el_ticket(self):
        row = type("TicketRow", (), {})()
        row.payload = self._ticket()
        row.estado = "Nuevo"
        locks = []

        class Query:
            def filter_by(self, **kwargs):
                return self

            def with_for_update(self):
                locks.append(True)
                return self

            def first(self):
                return row

        class TicketModel:
            query = Query()

        class Session:
            def __init__(self):
                self.commits = 0
                self.rollbacks = 0

            def commit(self):
                self.commits += 1

            def rollback(self):
                self.rollbacks += 1

        fake_db = type("DB", (), {"session": Session()})()
        with patch.object(tecman, "USE_DB", True), patch.object(
            tecman, "TicketDB", TicketModel, create=True
        ), patch.object(tecman, "db", fake_db, create=True):
            result = tecman._material_close_without_dispatch_transaction(
                self.TICKET_ID,
                "Administración DB",
                "duplicado",
                "Duplicado confirmado",
                "db-close-1",
            )
            repeated = tecman._material_close_without_dispatch_transaction(
                self.TICKET_ID,
                "Administración DB",
                "duplicado",
                "Duplicado confirmado",
                "db-close-1",
            )

        self.assertTrue(result["changed"])
        self.assertFalse(repeated["changed"])
        self.assertEqual(row.estado, "Cerrado")
        self.assertEqual(row.payload["cierre_sin_salida"]["actor"], "Administración DB")
        self.assertEqual(len(row.payload["cierre_sin_salida_historial"]), 1)
        self.assertEqual(len(locks), 2)
        self.assertEqual(fake_db.session.commits, 1)
        self.assertEqual(fake_db.session.rollbacks, 0)

    def test_fallo_de_persistencia_no_toca_ningun_archivo_operativo(self):
        baseline = self._runtime_snapshot()
        with patch.object(tecman, "_atomic_write", side_effect=OSError("fallo simulado")):
            with self.assertRaises(OSError):
                self._post()
        self.assertEqual(self._runtime_snapshot(), baseline)


if __name__ == "__main__":
    unittest.main()
