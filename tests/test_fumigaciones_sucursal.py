import io
import json
import os
import tempfile
import unittest
from pathlib import Path


_TEST_ROOT = tempfile.TemporaryDirectory()
os.environ["TECMAN_DATA_DIR"] = str(Path(_TEST_ROOT.name) / "data")
os.environ["TECMAN_UPLOADS_DIR"] = str(Path(_TEST_ROOT.name) / "uploads")
os.environ.pop("DATABASE_URL", None)

import app as tecman  # noqa: E402


class FumigacionesSucursalTest(unittest.TestCase):
    PDF_BYTES = b"%PDF-1.4\n% test fumigacion\n%%EOF\n"

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.data = self.root / "data"
        self.uploads = self.root / "uploads"
        self.data.mkdir()
        self.uploads.mkdir()
        self.original_paths = (
            tecman.TICKETS_FILE,
            tecman.NOTIF_ADMIN_FILE,
            tecman.FUMIGACION_REMITOS_DIR,
        )
        tecman.TICKETS_FILE = self.data / "tickets.json"
        tecman.NOTIF_ADMIN_FILE = self.data / "notif_admin.json"
        tecman.FUMIGACION_REMITOS_DIR = self.uploads / "fumigacion_remitos"
        tecman.FUMIGACION_REMITOS_DIR.mkdir(parents=True, exist_ok=True)
        tecman.USE_DB = False
        tecman.app.config.update(TESTING=True, SECRET_KEY="fumigaciones-test")
        self.client = tecman.app.test_client()

    def tearDown(self):
        (
            tecman.TICKETS_FILE,
            tecman.NOTIF_ADMIN_FILE,
            tecman.FUMIGACION_REMITOS_DIR,
        ) = self.original_paths
        self.temp.cleanup()

    def _save_ticket(self, **overrides):
        ticket = {
            "id": 901,
            "sucursal": "Sucursal 052",
            "sucursal_num": "052",
            "categoria": "Fumigaciones",
            "subcategoria": "Control de plagas",
            "descripcion": "Servicio mensual de fumigacion",
            "solicitante": "Sucursal",
            "prioridad": 2,
            "estado": "Abierto",
            "asignado": "Gerardo Goog",
            "asignado_proveedor": "Gerardo Goog",
            "creado": "2026-09-22T10:00:00",
            "actualizado": "2026-09-22T10:00:00",
            "notas": [],
        }
        ticket.update(overrides)
        tecman.TICKETS_FILE.write_text(json.dumps([ticket]), encoding="utf-8")
        return ticket

    def _provider_session(self):
        with self.client.session_transaction() as sess:
            sess.clear()
            sess["prov_user"] = "gerardo_goog"
            sess["prov_nombre"] = "Gerardo Goog"
            sess["prov_tipo_cuenta"] = "fumigacion"
            sess["prov_session_version"] = 1
            sess["_csrf_token"] = "csrf-test"

    def _sucursal_session(self, sucursal="Sucursal 052"):
        with self.client.session_transaction() as sess:
            sess.clear()
            sess["suc_user"] = "suc052"
            sess["suc_nombre"] = sucursal
            sess["_csrf_token"] = "csrf-test"

    def _admin_session(self):
        with self.client.session_transaction() as sess:
            sess.clear()
            sess["user"] = "admin-test"
            sess["nombre"] = "Admin Test"
            sess["rol"] = "admin"
            sess["_csrf_token"] = "csrf-test"

    def _subir_remito(self, ticket_id=901, filename="remito.pdf", content=None):
        return self.client.post(
            f"/suc/fumigaciones/{ticket_id}/remito",
            data={
                "_csrf_token": "csrf-test",
                "comentario": "Remito cargado por la sucursal",
                "remito": (io.BytesIO(content or self.PDF_BYTES), filename),
            },
            content_type="multipart/form-data",
        )

    def test_programacion_realizacion_carga_validacion_y_archivo_protegido(self):
        self._save_ticket()
        self._provider_session()
        planned = self.client.post(
            "/proveedor/ticket/901",
            data={"_csrf_token": "csrf-test", "accion": "planificado", "fecha_visita": "2026-09-25"},
        )
        self.assertEqual(planned.status_code, 302)
        realized = self.client.post(
            "/proveedor/ticket/901",
            data={"_csrf_token": "csrf-test", "accion": "relevado"},
        )
        self.assertEqual(realized.status_code, 302)
        ticket = tecman.load_tickets()[0]
        self.assertEqual(ticket["fumigacion_estado"], "realizada")
        self.assertEqual(ticket["remito_estado"], "pendiente_carga")
        self.assertIn("Fumigación realizada", ticket["notificaciones"][-1]["texto"])

        self._sucursal_session()
        panel = self.client.get("/suc/fumigaciones")
        self.assertEqual(panel.status_code, 200)
        self.assertIn(b"Subir remito", panel.data)
        uploaded = self._subir_remito()
        self.assertEqual(uploaded.status_code, 302)
        ticket = tecman.load_tickets()[0]
        self.assertEqual(ticket["remito_estado"], "pendiente_validacion")
        self.assertEqual(len(ticket["remitos_fumigacion"]), 1)
        filename = ticket["remitos_fumigacion"][0]["archivo"]
        self.assertTrue((tecman.FUMIGACION_REMITOS_DIR / "901" / filename).is_file())
        response = self.client.get(f"/fumigaciones/901/remitos/{filename}")
        self.assertEqual(response.status_code, 200)
        response.close()

        self._sucursal_session("Sucursal 167")
        self.assertEqual(self.client.get(f"/fumigaciones/901/remitos/{filename}").status_code, 403)
        self._admin_session()
        response = self.client.get(f"/fumigaciones/901/remitos/{filename}")
        self.assertEqual(response.status_code, 200)
        response.close()
        validated = self.client.post(
            "/admin/ticket/901",
            data={
                "_csrf_token": "csrf-test",
                "accion": "validar_remito_fumigacion",
                "remito_id": ticket["remito_actual_id"],
            },
        )
        self.assertEqual(validated.status_code, 302)
        ticket = tecman.load_tickets()[0]
        self.assertEqual(ticket["remito_estado"], "validado")
        self.assertTrue(any(e["accion"] == "remito_validado" for e in ticket["fumigacion_historial"]))

    def test_deteccion_estructurada_admite_tipo_cuenta_y_rechaza_texto_amplio(self):
        self.assertTrue(tecman._ticket_es_fumigacion({"tipo_cuenta": "fumigacion"}))
        self.assertTrue(tecman._ticket_es_fumigacion({"workflow": "fumigacion_remito"}))
        self.assertFalse(tecman._ticket_es_fumigacion({
            "categoria": "Mantenimiento",
            "descripcion": "Hay olor luego de una fumigación anterior",
        }))

    def test_devolucion_permita_recarga_y_validaciones_no_dejan_archivos(self):
        self._save_ticket(fumigacion_estado="realizada", remito_estado="pendiente_carga")
        self._sucursal_session()
        missing = self._subir_remito(filename="remito.txt", content=b"no pdf")
        self.assertEqual(missing.status_code, 400)
        remitos_dir = tecman.FUMIGACION_REMITOS_DIR / "901"
        self.assertEqual(list(remitos_dir.glob("*")) if remitos_dir.exists() else [], [])

        self.assertEqual(self._subir_remito().status_code, 302)
        ticket = tecman.load_tickets()[0]
        remito_id = ticket["remito_actual_id"]
        self._admin_session()
        without_reason = self.client.post(
            "/admin/ticket/901",
            data={"_csrf_token": "csrf-test", "accion": "devolver_remito_fumigacion", "remito_id": remito_id},
        )
        self.assertEqual(without_reason.status_code, 400)
        returned = self.client.post(
            "/admin/ticket/901",
            data={
                "_csrf_token": "csrf-test",
                "accion": "devolver_remito_fumigacion",
                "remito_id": remito_id,
                "observacion": "No se lee el numero de remito",
            },
        )
        self.assertEqual(returned.status_code, 302)
        self.assertEqual(tecman.load_tickets()[0]["remito_estado"], "pendiente_carga")

        self._sucursal_session()
        self.assertEqual(self._subir_remito(filename="remito-corregido.pdf").status_code, 302)
        ticket = tecman.load_tickets()[0]
        self.assertEqual(ticket["remito_estado"], "pendiente_validacion")
        self.assertEqual(len(ticket["remitos_fumigacion"]), 2)


if __name__ == "__main__":
    unittest.main()
