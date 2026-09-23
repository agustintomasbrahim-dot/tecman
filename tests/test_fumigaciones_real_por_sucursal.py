import copy
import io
import json
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
from models import FumigacionDB  # noqa: E402

PDF = b"%PDF-1.4\nfumigacion real\n%%EOF\n"


class FumigacionesRealPorSucursalTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.data = self.root / "data"
        self.uploads = self.root / "uploads"
        self.data.mkdir()
        self.uploads.mkdir()
        self.original_globals = (
            tecman.FUMIGACIONES_FILE,
            tecman.TICKETS_FILE,
            tecman.USE_DB,
        )
        self.config_keys = (
            "FUMIGACIONES_LOAD",
            "FUMIGACIONES_SAVE",
            "FUMIGACIONES_PROVIDER_NAMES",
            "FUMIGACIONES_PORTFOLIO",
            "FUMIGACIONES_BRANCH_INFO",
            "FUMIGACIONES_NORMALIZE_BRANCH",
            "FUMIGACIONES_BRANCH_SCOPE",
            "FUMIGACIONES_REFRESH_SESSION",
            "FUMIGACIONES_UPLOADS_DIR",
            "FUMIGACIONES_MAX_FILE_BYTES",
        )
        self.original_config = {key: tecman.app.config.get(key) for key in self.config_keys}
        tecman.FUMIGACIONES_FILE = self.data / "fumigaciones.json"
        tecman.TICKETS_FILE = self.data / "tickets.json"
        tecman.USE_DB = False
        tecman.save_tickets([])

        def portfolio(names):
            names = set(names or [])
            entries = []
            if "Cesar Ricardo Fratini" in names:
                entries.extend({
                    "proveedor": "Cesar Ricardo Fratini",
                    "sucursal_num": f"{number:03d}",
                    "sucursal": f"Sucursal {number:03d}",
                } for number in range(1, 197))
            if "Gerardo Goog" in names:
                entries.append({
                    "proveedor": "Gerardo Goog",
                    "sucursal_num": "220",
                    "sucursal": "Sucursal 220",
                })
            return entries

        tecman.app.config.update(
            TESTING=True,
            SECRET_KEY="fumigaciones-real-test",
            FUMIGACIONES_LOAD=tecman.load_fumigaciones,
            FUMIGACIONES_SAVE=tecman.save_fumigaciones,
            FUMIGACIONES_PROVIDER_NAMES=tecman._proveedor_nombres_usuario,
            FUMIGACIONES_PORTFOLIO=portfolio,
            FUMIGACIONES_BRANCH_INFO=lambda num: {
                "tienda": f"Local {num}",
                "direccion": f"Calle {num}",
                "ciudad": "Ciudad de prueba",
                "provincia": "Provincia de prueba",
                "marca": "DX",
            },
            FUMIGACIONES_NORMALIZE_BRANCH=tecman._sucursal_num_from_value,
            FUMIGACIONES_BRANCH_SCOPE=tecman._fumigacion_scope_sucursal,
            FUMIGACIONES_REFRESH_SESSION=tecman._refresh_proveedor_session_tipo,
            FUMIGACIONES_UPLOADS_DIR=str(self.uploads / "fumigaciones"),
            FUMIGACIONES_MAX_FILE_BYTES=1024 * 1024,
        )
        self.client = tecman.app.test_client()

    def tearDown(self):
        tecman.FUMIGACIONES_FILE, tecman.TICKETS_FILE, tecman.USE_DB = self.original_globals
        tecman.app.config.update(self.original_config)
        self.temp.cleanup()

    def provider(self, user="frattini", name="Cesar Ricardo Fratini"):
        with self.client.session_transaction() as sess:
            sess.clear()
            sess.update(
                prov_user=user,
                prov_nombre=name,
                prov_tipo_cuenta="fumigacion",
                prov_session_version=1,
                _csrf_token="csrf",
            )

    def branch(self, number="001"):
        with self.client.session_transaction() as sess:
            sess.clear()
            sess.update(suc_user=f"suc-{number}", suc_nombre=f"Sucursal {number}", _csrf_token="csrf")

    def admin(self):
        with self.client.session_transaction() as sess:
            sess.clear()
            sess.update(user="admin", nombre="Administración", rol="admin", _csrf_token="csrf")

    def schedule(self, number="001", date="2026-10-05"):
        return self.client.post(
            f"/proveedor/fumigaciones/sucursal/{number}/programar",
            data={"_csrf_token": "csrf", "fecha_programada": date, "observacion": "Coordinar apertura"},
        )

    def record(self):
        records = tecman.load_fumigaciones()
        self.assertEqual(len(records), 1)
        return records[0]

    def complete(self, record_id):
        return self.client.post(
            f"/proveedor/fumigaciones/visita/{record_id}/relevamiento",
            data={
                "_csrf_token": "csrf",
                "fecha_realizada": "2026-10-05",
                "trabajo_realizado": "Aplicación preventiva en salón y depósito",
                "plagas_detectadas": "Sin actividad",
                "productos_aplicados": "Gel y aspersión autorizada",
                "observaciones": "Trabajo conforme",
                "remito": (io.BytesIO(PDF), "remito.pdf"),
                "certificado": (io.BytesIO(PDF), "certificado.pdf"),
            },
            content_type="multipart/form-data",
        )

    def test_cartera_de_196_sucursales_sin_tickets_y_detalle(self):
        self.provider()
        panel = self.client.get("/proveedor/fumigaciones")
        self.assertEqual(panel.status_code, 200)
        html = panel.get_data(as_text=True)
        self.assertIn("196 sucursal(es)", html)
        self.assertEqual(html.count("/proveedor/fumigaciones/sucursal/"), 196)
        self.assertNotIn("Ticket #", html)
        detail = self.client.get("/proveedor/fumigaciones/sucursal/196")
        self.assertEqual(detail.status_code, 200)
        self.assertIn("Local 196", detail.get_data(as_text=True))

    def test_programacion_y_aviso_a_sucursal_son_idempotentes(self):
        self.provider()
        self.assertEqual(self.schedule().status_code, 302)
        self.assertEqual(self.schedule().status_code, 302)
        record = self.record()
        self.assertEqual(record["estado"], "Programada")
        self.assertEqual(len(record["notificaciones_sucursal"]), 1)
        self.assertEqual(len(record["historial"]), 1)
        self.branch("001")
        page = self.client.get("/suc/fumigaciones")
        self.assertEqual(page.status_code, 200)
        body = page.get_data(as_text=True)
        self.assertIn("Fumigación programada para 2026-10-05", body)
        self.assertIn("Cesar Ricardo Fratini", body)

    def test_relevamiento_remito_historial_validacion_y_archivos_protegidos(self):
        self.provider()
        self.schedule()
        record_id = self.record()["id"]
        response = self.complete(record_id)
        self.assertEqual(response.status_code, 302)
        record = self.record()
        self.assertEqual(record["estado"], "Realizada")
        self.assertEqual(record["relevamiento"]["trabajo_realizado"], "Aplicación preventiva en salón y depósito")
        self.assertEqual([event["accion"] for event in record["historial"]], ["Visita programada", "Relevamiento registrado"])
        remito = record["documentos"]["remito"]
        self.assertRegex(remito["archivo"], r"^[a-f0-9]{32}\.pdf$")
        self.assertTrue((self.uploads / "fumigaciones" / record_id / remito["archivo"]).is_file())
        served = self.client.get(f"/proveedor/fumigaciones/visita/{record_id}/archivo/{remito['archivo']}")
        self.assertEqual(served.status_code, 200)
        served.close()
        self.assertEqual(self.client.get(f"/proveedor/fumigaciones/visita/{record_id}/archivo/no-referenciado.pdf").status_code, 404)
        self.assertEqual(self.client.get(f"/static/uploads/fumigaciones/{record_id}/{remito['archivo']}").status_code, 404)

        self.admin()
        self.assertEqual(self.client.post(
            f"/admin/proveedores/fumigaciones/visita/{record_id}/validar",
            data={"_csrf_token": "csrf"},
        ).status_code, 302)
        record = self.record()
        self.assertEqual(record["estado"], "Validada")
        self.assertEqual(record["historial"][-1]["accion"], "Visita validada")

    def test_aislamiento_entre_proveedores_sucursales_y_acceso_cruzado(self):
        self.provider()
        self.schedule()
        record_id = self.record()["id"]
        self.complete(record_id)
        filename = self.record()["documentos"]["remito"]["archivo"]

        self.provider("gerardo_goog", "Gerardo Goog")
        self.assertEqual(self.client.get("/proveedor/fumigaciones/sucursal/001").status_code, 403)
        self.assertEqual(self.client.get(f"/proveedor/fumigaciones/visita/{record_id}/archivo/{filename}").status_code, 403)
        before = copy.deepcopy(tecman.load_fumigaciones())
        self.assertEqual(self.schedule("001", "2026-10-06").status_code, 403)
        self.assertEqual(tecman.load_fumigaciones(), before)

        self.branch("002")
        self.assertEqual(self.client.get(f"/suc/fumigaciones/visita/{record_id}/archivo/{filename}").status_code, 403)
        self.branch("001")
        owned = self.client.get(f"/suc/fumigaciones/visita/{record_id}/archivo/{filename}")
        self.assertEqual(owned.status_code, 200)
        owned.close()

    def test_rutas_sin_sesion_csrf_y_upload_invalido_no_mutan(self):
        self.assertEqual(self.client.get("/proveedor/fumigaciones").status_code, 302)
        self.assertEqual(self.client.get("/proveedor/fumigaciones/sucursal/001").status_code, 302)
        self.assertEqual(self.client.post("/proveedor/fumigaciones/sucursal/001/programar").status_code, 302)
        self.assertEqual(self.client.get("/admin/proveedores/fumigaciones").status_code, 302)

        self.provider()
        self.assertEqual(self.schedule().status_code, 302)
        record_id = self.record()["id"]
        before = copy.deepcopy(tecman.load_fumigaciones())
        no_csrf = self.client.post(
            f"/proveedor/fumigaciones/visita/{record_id}/relevamiento",
            data={"trabajo_realizado": "No guardar"},
        )
        self.assertEqual(no_csrf.status_code, 400)
        self.assertEqual(tecman.load_fumigaciones(), before)
        invalid = self.client.post(
            f"/proveedor/fumigaciones/visita/{record_id}/relevamiento",
            data={
                "_csrf_token": "csrf",
                "fecha_realizada": "2026-10-05",
                "trabajo_realizado": "Trabajo",
                "productos_aplicados": "Producto",
                "remito": (io.BytesIO(b"archivo falso"), "remito.pdf"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(tecman.load_fumigaciones(), before)
        self.assertFalse((self.uploads / "fumigaciones" / record_id).exists())

    def test_fallback_json_y_adaptador_postgresql(self):
        payload = [{
            "id": "FUM-DB",
            "sucursal_num": "001",
            "proveedor": "Cesar Ricardo Fratini",
            "estado": "Programada",
            "fecha_programada": "2026-10-05",
        }]
        tecman.save_fumigaciones(payload)
        self.assertEqual(json.loads(tecman.FUMIGACIONES_FILE.read_text(encoding="utf-8")), payload)
        self.assertEqual(tecman.load_fumigaciones(), payload)

        model = FumigacionDB.from_dict(payload[0])
        self.assertEqual(model.id, "FUM-DB")
        self.assertEqual(model.sucursal_num, "001")
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
