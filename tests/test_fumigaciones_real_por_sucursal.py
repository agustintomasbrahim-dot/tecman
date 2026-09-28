import copy
import io
import json
import os
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

_TEST_ROOT = tempfile.TemporaryDirectory()
os.environ["TECMAN_DATA_DIR"] = str(Path(_TEST_ROOT.name) / "data")
os.environ["TECMAN_UPLOADS_DIR"] = str(Path(_TEST_ROOT.name) / "uploads")
os.environ.pop("DATABASE_URL", None)

import app as tecman  # noqa: E402
from models import FumigacionDB  # noqa: E402

PDF = b"%PDF-1.4\nremito firmado\n%%EOF\n"
FRATINI = ["014", "020", "035", "036", "049", "053", "054", "102", "111", "121", "125", "141", "147", "148", "156", "157", "165", "170", "176", "177", "183", "184", "185", "186", "192", "196", "198", "200", "202", "208", "213", "214", "219", "221", "228", "237", "238"]
INGAM = ["011", "051", "058", "065", "077", "080", "082", "083", "142", "146", "158", "171", "188", "194", "195", "209", "211", "216", "222"]


class FumigacionesRealPorSucursalTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.data = self.root / "data"
        self.uploads = self.root / "uploads"
        self.data.mkdir()
        self.uploads.mkdir()
        self.original_globals = (tecman.FUMIGACIONES_FILE, tecman.TICKETS_FILE, tecman.USE_DB)
        self.config_keys = (
            "TECMAN_SESSION_AUTH_VALIDATOR", "FUMIGACIONES_LOAD", "FUMIGACIONES_SAVE",
            "FUMIGACIONES_PROVIDER_NAMES", "FUMIGACIONES_PORTFOLIO", "FUMIGACIONES_BRANCH_INFO",
            "FUMIGACIONES_NORMALIZE_BRANCH", "FUMIGACIONES_BRANCH_SCOPE",
            "FUMIGACIONES_REFRESH_SESSION", "FUMIGACIONES_NOTIFY_SCHEDULE",
            "FUMIGACIONES_UPLOADS_DIR", "FUMIGACIONES_MAX_FILE_BYTES",
        )
        self.original_config = {key: tecman.app.config.get(key) for key in self.config_keys}
        tecman.FUMIGACIONES_FILE = self.data / "fumigaciones.json"
        tecman.TICKETS_FILE = self.data / "tickets.json"
        tecman.USE_DB = False
        tecman.save_tickets([])
        self.admin_notices = []
        tecman.app.config.update(
            TESTING=True,
            SECRET_KEY="fumigaciones-real-test",
            TECMAN_SESSION_AUTH_VALIDATOR=lambda: True,
            FUMIGACIONES_LOAD=tecman.load_fumigaciones,
            FUMIGACIONES_SAVE=tecman.save_fumigaciones,
            FUMIGACIONES_PROVIDER_NAMES=lambda: [self._session_provider_name()],
            FUMIGACIONES_PORTFOLIO=tecman._fumigaciones_portfolio,
            FUMIGACIONES_BRANCH_INFO=lambda num: {
                "tienda": f"Local {num}", "direccion": f"Calle {num}",
                "ciudad": "Ciudad de prueba", "provincia": "Provincia de prueba", "marca": "DX",
            },
            FUMIGACIONES_NORMALIZE_BRANCH=tecman._sucursal_num_from_value,
            FUMIGACIONES_BRANCH_SCOPE=tecman._fumigacion_scope_sucursal,
            FUMIGACIONES_REFRESH_SESSION=lambda: "fumigacion",
            FUMIGACIONES_NOTIFY_SCHEDULE=lambda visit: self.admin_notices.append(copy.deepcopy(visit)),
            FUMIGACIONES_UPLOADS_DIR=str(self.uploads / "fumigaciones"),
            FUMIGACIONES_MAX_FILE_BYTES=1024 * 1024,
        )
        self.client = tecman.app.test_client()
        self.visit_date = (date.today() + timedelta(days=5)).isoformat()

    def tearDown(self):
        tecman.FUMIGACIONES_FILE, tecman.TICKETS_FILE, tecman.USE_DB = self.original_globals
        tecman.app.config.update(self.original_config)
        self.temp.cleanup()

    def _session_provider_name(self):
        from flask import session
        return session.get("prov_nombre", "")

    def provider(self, user="frattini", name="Cesar Ricardo Fratini"):
        with self.client.session_transaction() as sess:
            sess.clear()
            sess.update(prov_user=user, prov_nombre=name, prov_tipo_cuenta="fumigacion", prov_session_version=1, _csrf_token="csrf")

    def branch(self, number="014"):
        with self.client.session_transaction() as sess:
            sess.clear()
            sess.update(suc_user=f"suc{number}", suc_nombre=f"Sucursal {number}", _csrf_token="csrf")

    def admin(self):
        with self.client.session_transaction() as sess:
            sess.clear()
            sess.update(user="admin", nombre="Administración", rol="admin", _csrf_token="csrf")

    def schedule(self, number="014", visit_date=None):
        return self.client.post(
            f"/proveedor/fumigaciones/sucursal/{number}/programar",
            data={"_csrf_token": "csrf", "fecha_programada": visit_date or self.visit_date},
        )

    def record(self):
        records = tecman.load_fumigaciones()
        self.assertEqual(len(records), 1)
        return records[0]

    def close(self, record_id, content=PDF, filename="remito-firmado.pdf", csrf="csrf"):
        return self.client.post(
            f"/proveedor/fumigaciones/visita/{record_id}/cerrar",
            data={"_csrf_token": csrf, "remito": (io.BytesIO(content), filename)},
            content_type="multipart/form-data",
        )

    def test_carteras_canonicas_salen_del_catalogo_con_cantidades_e_interseccion_exactas(self):
        fratini = [row["sucursal_num"] for row in tecman._fumigaciones_portfolio({"Cesar Ricardo Fratini"})]
        ingam = [row["sucursal_num"] for row in tecman._fumigaciones_portfolio({"INGAM Control de Plagas SRL"})]
        self.assertEqual(fratini, FRATINI)
        self.assertEqual(ingam, INGAM)
        self.assertEqual((len(fratini), len(ingam)), (37, 19))
        self.assertFalse(set(fratini) & set(ingam))
        self.assertEqual(tecman.FUMIGACIONES_SIMPLE_PORTFOLIOS["Cesar Ricardo Fratini"], set(FRATINI))
        self.assertEqual(tecman.FUMIGACIONES_SIMPLE_PORTFOLIOS["INGAM Control de Plagas SRL"], set(INGAM))

    def test_paneles_muestran_solo_la_cartera_propia_y_sin_formularios_largos(self):
        self.provider()
        page = self.client.get("/proveedor/fumigaciones")
        body = page.get_data(as_text=True)
        self.assertEqual(page.status_code, 200)
        self.assertIn("37 sucursal(es)", body)
        self.assertEqual(body.count("/proveedor/fumigaciones/sucursal/"), 37)
        self.assertIn("SUCURSAL 014", body)
        self.assertNotIn("SUCURSAL 011", body)
        self.schedule()
        detail = self.client.get("/proveedor/fumigaciones/sucursal/014").get_data(as_text=True)
        self.assertIn("Cargar remito y cerrar visita", detail)
        for forbidden in ("Trabajo realizado", "Productos aplicados", "Plagas detectadas", "Certificado opcional"):
            self.assertNotIn(forbidden, detail)

        self.provider("ingam", "INGAM Control de Plagas SRL")
        body = self.client.get("/proveedor/fumigaciones").get_data(as_text=True)
        self.assertIn("19 sucursal(es)", body)
        self.assertIn("SUCURSAL 011", body)
        self.assertNotIn("SUCURSAL 014", body)
        self.assertEqual(self.client.get("/proveedor/fumigaciones/sucursal/014").status_code, 403)

    def test_programacion_es_idempotente_y_visible_para_admin_y_sucursal(self):
        self.provider()
        self.assertEqual(self.schedule().status_code, 302)
        self.assertEqual(self.schedule().status_code, 302)
        record = self.record()
        self.assertEqual(record["estado"], "Programada")
        self.assertEqual(len(record["notificaciones_sucursal"]), 1)
        self.assertEqual(len(record["historial"]), 1)
        self.assertEqual(len(self.admin_notices), 1)

        self.branch("014")
        page = self.client.get("/suc/fumigaciones")
        self.assertEqual(page.status_code, 200)
        self.assertIn(f"Fumigación programada para {self.visit_date}", page.get_data(as_text=True))
        self.admin()
        admin_page = self.client.get("/admin/proveedores/fumigaciones")
        self.assertEqual(admin_page.status_code, 200)
        self.assertIn(record["id"], admin_page.get_data(as_text=True))

    def test_remito_firmado_cierra_directamente_y_descarga_es_protegida(self):
        self.provider()
        self.schedule()
        record_id = self.record()["id"]
        response = self.close(record_id)
        self.assertEqual(response.status_code, 302)
        record = self.record()
        self.assertEqual(record["estado"], "Cerrada")
        self.assertIn("fecha_cierre", record)
        self.assertNotIn("relevamiento", record)
        self.assertEqual([event["accion"] for event in record["historial"]], ["Visita programada", "Visita cerrada"])
        remito = record["documentos"]["remito_firmado"]
        self.assertRegex(remito["archivo"], r"^[a-f0-9]{32}\.pdf$")
        path = self.uploads / "fumigaciones" / record_id / remito["archivo"]
        self.assertTrue(path.is_file())
        served = self.client.get(f"/proveedor/fumigaciones/visita/{record_id}/archivo/{remito['archivo']}")
        self.assertEqual(served.status_code, 200)
        served.close()
        self.assertEqual(self.client.get(f"/proveedor/fumigaciones/visita/{record_id}/archivo/no-referenciado.pdf").status_code, 404)
        self.assertEqual(self.client.get(f"/static/uploads/fumigaciones/{record_id}/{remito['archivo']}").status_code, 404)
        self.assertEqual(self.close(record_id).status_code, 409)

    def test_ids_y_archivos_cruzados_quedan_bloqueados_sin_mutar(self):
        self.provider()
        self.schedule()
        record_id = self.record()["id"]
        self.close(record_id)
        filename = self.record()["documentos"]["remito_firmado"]["archivo"]
        before = copy.deepcopy(tecman.load_fumigaciones())

        self.provider("ingam", "INGAM Control de Plagas SRL")
        self.assertEqual(self.client.get(f"/proveedor/fumigaciones/visita/{record_id}/archivo/{filename}").status_code, 403)
        self.assertEqual(self.client.post(f"/proveedor/fumigaciones/visita/{record_id}/cerrar", data={"_csrf_token": "csrf"}).status_code, 403)
        self.assertEqual(self.schedule("014").status_code, 403)
        self.assertEqual(tecman.load_fumigaciones(), before)

        self.branch("011")
        self.assertEqual(self.client.get(f"/suc/fumigaciones/visita/{record_id}/archivo/{filename}").status_code, 403)
        self.branch("014")
        owned = self.client.get(f"/suc/fumigaciones/visita/{record_id}/archivo/{filename}")
        self.assertEqual(owned.status_code, 200)
        owned.close()

    def test_sin_sesion_csrf_firma_extension_y_tamano_invalidos_no_mutan(self):
        self.assertEqual(self.client.get("/proveedor/fumigaciones").status_code, 302)
        self.assertEqual(self.client.post("/proveedor/fumigaciones/sucursal/014/programar").status_code, 302)
        self.provider()
        self.schedule()
        record_id = self.record()["id"]
        before = copy.deepcopy(tecman.load_fumigaciones())
        cases = (
            (PDF, "remito.pdf", "incorrecto"),
            (b"archivo falso", "remito.pdf", "csrf"),
            (PDF, "remito.exe", "csrf"),
            (b"%PDF-" + b"x" * (1024 * 1024), "grande.pdf", "csrf"),
        )
        for content, filename, csrf in cases:
            with self.subTest(filename=filename, csrf=csrf, size=len(content)):
                self.assertEqual(self.close(record_id, content, filename, csrf).status_code, 400)
                self.assertEqual(tecman.load_fumigaciones(), before)
        self.assertFalse((self.uploads / "fumigaciones" / record_id).exists())

    def test_programar_y_cerrar_no_crean_tickets(self):
        original_tickets = tecman.TICKETS_FILE.read_bytes()
        self.provider()
        self.schedule()
        self.close(self.record()["id"])
        self.assertEqual(tecman.TICKETS_FILE.read_bytes(), original_tickets)

    def test_otro_fumigador_conserva_su_relevamiento_y_validacion_existentes(self):
        self.provider("gerardo_goog", "Gerardo Goog")
        self.assertEqual(self.schedule("052").status_code, 302)
        record_id = self.record()["id"]
        detail = self.client.get("/proveedor/fumigaciones/sucursal/052").get_data(as_text=True)
        self.assertIn("Trabajo realizado", detail)
        self.assertIn("Certificado opcional", detail)
        self.assertNotIn("Cargar remito y cerrar visita", detail)
        self.assertEqual(self.close(record_id).status_code, 403)
        completed = self.client.post(
            f"/proveedor/fumigaciones/visita/{record_id}/relevamiento",
            data={
                "_csrf_token": "csrf", "fecha_realizada": self.visit_date,
                "trabajo_realizado": "Aplicación preventiva",
                "productos_aplicados": "Producto autorizado",
                "remito": (io.BytesIO(PDF), "remito.pdf"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(completed.status_code, 302)
        self.assertEqual(self.record()["estado"], "Realizada")
        self.admin()
        validated = self.client.post(
            f"/admin/proveedores/fumigaciones/visita/{record_id}/validar",
            data={"_csrf_token": "csrf"},
        )
        self.assertEqual(validated.status_code, 302)
        self.assertEqual(self.record()["estado"], "Validada")

    def test_fallback_json_y_adaptador_postgresql(self):
        payload = [{"id": "FUM-DB", "sucursal_num": "014", "proveedor": "Cesar Ricardo Fratini", "estado": "Programada", "fecha_programada": self.visit_date}]
        tecman.save_fumigaciones(payload)
        self.assertEqual(json.loads(tecman.FUMIGACIONES_FILE.read_text(encoding="utf-8")), payload)
        self.assertEqual(tecman.load_fumigaciones(), payload)
        model = FumigacionDB.from_dict(payload[0])
        self.assertEqual(model.to_dict(), payload[0])

        tecman.USE_DB = True
        with patch.object(tecman, "FumigacionDB", FumigacionDB, create=True):
            with patch.object(tecman, "_db_list", return_value=copy.deepcopy(payload)) as db_list:
                self.assertEqual(tecman.load_fumigaciones(), payload)
                db_list.assert_called_once_with(FumigacionDB)
            with patch.object(tecman, "_db_replace") as db_replace, patch.object(tecman, "_atomic_write") as atomic_write:
                tecman.save_fumigaciones(payload)
                db_replace.assert_called_once_with(FumigacionDB, payload)
                atomic_write.assert_called_once_with(tecman.FUMIGACIONES_FILE, payload)


if __name__ == "__main__":
    unittest.main()
