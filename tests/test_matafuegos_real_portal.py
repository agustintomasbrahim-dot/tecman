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

PDF = b"%PDF-1.4\nportal test\n%%EOF\n"
PNG = b"\x89PNG\r\n\x1a\nportal-test"


class MatafuegosRealPorSucursalesTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.data = root / "data"; self.data.mkdir()
        self.uploads = root / "uploads"; self.uploads.mkdir()
        self.original = {
            "MATAFUEGOS_FILE": tecman.MATAFUEGOS_FILE,
            "MATAFUEGOS_VISITAS_FILE": tecman.MATAFUEGOS_VISITAS_FILE,
            "NOTIF_ADMIN_FILE": tecman.NOTIF_ADMIN_FILE,
            "PROVEEDOR_USERS_FILE": tecman.PROVEEDOR_USERS_FILE,
            "TICKETS_FILE": tecman.TICKETS_FILE,
            "USE_DB": tecman.USE_DB,
            "PROVEEDORES": tecman.PROVEEDORES,
        }
        tecman.MATAFUEGOS_FILE = self.data / "matafuegos.json"
        tecman.MATAFUEGOS_VISITAS_FILE = self.data / "matafuegos_visitas.json"
        tecman.NOTIF_ADMIN_FILE = self.data / "notif_admin.json"
        tecman.PROVEEDOR_USERS_FILE = self.data / "proveedor_users.json"
        tecman.TICKETS_FILE = self.data / "tickets.json"
        tecman.USE_DB = False
        tecman.PROVEEDORES = [
            {"nombre": "Proveedor A", "tipo": "Matafuegos", "workflow": "matafuegos_remito_vencimiento", "sucursales": ["101", "102"]},
            {"nombre": "Proveedor B", "tipo": "Matafuegos", "workflow": "matafuegos_remito_vencimiento", "sucursales": ["202"]},
        ]
        inventory = [
            self._equipment("eq-101-a", "101", "Local Uno", "SER-101-A"),
            self._equipment("eq-101-b", "101", "Local Uno", "SER-101-B"),
            self._equipment("eq-102", "102", "Local Dos", "SER-102"),
            self._equipment("eq-202", "202", "Local Otro", "SER-202"),
        ]
        tecman.save_matafuegos({"matafuegos": inventory})
        tecman.save_matafuegos_visitas({"visitas": []})
        tecman.save_notif_admin({"notificaciones": []})
        tecman.TICKETS_FILE.write_text(json.dumps([{"id": 77, "descripcion": "intacto"}]), encoding="utf-8")
        users = {
            "proveedor_a": {"password_hash": tecman._hash_password("Proveedor-A-2026"), "nombre": "Proveedor A", "tipo_cuenta": "matafuegos", "proveedores": ["Proveedor A"], "status": "active", "session_version": 1},
            "proveedor_b": {"password_hash": tecman._hash_password("Proveedor-B-2026"), "nombre": "Proveedor B", "tipo_cuenta": "matafuegos", "proveedores": ["Proveedor B"], "status": "active", "session_version": 1},
        }
        tecman.PROVEEDOR_USERS_FILE.write_text(json.dumps({"users": users}), encoding="utf-8")
        tecman.app.config.update(
            TESTING=True, SECRET_KEY="test-only",
            MATAFUEGOS_REAL_UPLOADS_DIR=str(self.uploads / "matafuegos_real"),
            MATAFUEGOS_REAL_MAX_FILE_BYTES=1024 * 1024,
        )
        self.client = tecman.app.test_client()
        self.tomorrow = (date.today() + timedelta(days=1)).isoformat()
        self.recharge = date.today().isoformat()
        self.expiry = date(date.today().year + 1, date.today().month, min(date.today().day, 28)).isoformat()

    def tearDown(self):
        for name, value in self.original.items():
            setattr(tecman, name, value)
        self.temp.cleanup()

    @staticmethod
    def _equipment(item_id, branch, local, serial):
        return {"id": item_id, "sucursal": f"Sucursal {branch}", "sucursal_num": branch, "local_nombre": local, "tipo": "ABC", "capacidad": "5 KG", "cantidad": 1, "ubicacion": "Salón", "nro_extintor": serial, "fecha_carga": "2025-01-01", "fecha_vencimiento": "2026-01-01"}

    def provider(self, key="proveedor_a", name="Proveedor A"):
        with self.client.session_transaction() as sess:
            sess.clear(); sess.update(prov_user=key, prov_nombre=name, prov_tipo_cuenta="matafuegos", prov_session_version=1, _csrf_token="csrf")

    def admin(self):
        with self.client.session_transaction() as sess:
            sess.clear(); sess.update(user="admin", nombre="Administración", rol="admin", _csrf_token="csrf")

    def branch(self, branch):
        with self.client.session_transaction() as sess:
            sess.clear(); sess.update(suc_user=f"suc-{branch}", suc_nombre=f"Sucursal {branch}", _csrf_token="csrf")

    def visits(self):
        return tecman.load_matafuegos_visitas()["visitas"]

    def result(self, serial, **extra):
        data = {"_csrf_token": "csrf", "encontrado": "si", "estado_fisico": "Bueno", "trabajo_realizado": "recargado", "fecha_recarga": self.recharge, "proximo_vencimiento": self.expiry, "identificacion": serial, "ubicacion": "Depósito", "observacion": "Mantenimiento anual"}
        data.update(extra)
        return data

    def schedule(self, branch="101"):
        return self.client.post(f"/proveedor/matafuegos/sucursal/{branch}/programar", data={"_csrf_token": "csrf", "fecha_programada": self.tomorrow})

    def test_cartera_lista_sucursales_inventario_y_rechaza_acceso_cruzado(self):
        tickets_before = tecman.TICKETS_FILE.read_bytes()
        self.provider()
        panel = self.client.get("/proveedor/matafuegos")
        body = panel.get_data(as_text=True)
        self.assertEqual(panel.status_code, 200)
        self.assertIn("SUCURSAL 101", body); self.assertIn("SUCURSAL 102", body)
        self.assertNotIn("SUCURSAL 202", body); self.assertNotIn("TICKET #", body.upper())
        detail = self.client.get("/proveedor/matafuegos/sucursal/101")
        self.assertEqual(detail.status_code, 200)
        self.assertIn("SER-101-A", detail.get_data(as_text=True)); self.assertNotIn("SER-202", detail.get_data(as_text=True))
        self.assertEqual(self.client.get("/proveedor/matafuegos/sucursal/202").status_code, 403)
        self.assertEqual(self.client.post("/proveedor/matafuegos/sucursal/202/programar", data={"_csrf_token": "csrf", "fecha_programada": self.tomorrow}).status_code, 403)
        self.assertEqual(tickets_before, tecman.TICKETS_FILE.read_bytes())

    def test_rutas_sin_sesion_y_csrf_no_mutan(self):
        self.assertEqual(self.client.get("/proveedor/matafuegos").status_code, 302)
        self.assertEqual(self.client.get("/proveedor/matafuegos/sucursal/101").status_code, 302)
        self.assertEqual(self.client.get("/admin/proveedores/matafuegos").status_code, 302)
        self.provider(); before = copy.deepcopy(self.visits())
        response = self.client.post("/proveedor/matafuegos/sucursal/101/programar", data={"fecha_programada": self.tomorrow})
        self.assertEqual(response.status_code, 400); self.assertEqual(before, self.visits())

    def test_programacion_y_aviso_son_idempotentes_y_visibles_para_sucursal(self):
        self.provider()
        self.assertEqual(self.schedule().status_code, 302)
        first_visits = copy.deepcopy(self.visits())
        first_notifs = copy.deepcopy(tecman.load_notif_admin()["notificaciones"])
        self.assertEqual(len(first_visits), 1); self.assertEqual(len(first_visits[0]["avisos_sucursal"]), 1)
        self.assertEqual(self.schedule().status_code, 302)
        self.assertEqual(first_visits, self.visits())
        self.assertEqual(first_notifs, tecman.load_notif_admin()["notificaciones"])
        self.branch("101")
        page = self.client.get("/suc/matafuegos").get_data(as_text=True)
        self.assertIn("Visita de matafuegos programada", page); self.assertIn(self.tomorrow, page); self.assertIn("Proveedor A", page)

    def test_mantenimiento_fotos_documentos_devolucion_validacion_e_historial(self):
        tickets_before = tecman.TICKETS_FILE.read_bytes()
        self.provider(); self.schedule()
        for item_id, serial in (("eq-101-a", "SER-101-A-NUEVA"), ("eq-101-b", "SER-101-B-NUEVA")):
            response = self.client.post(f"/proveedor/matafuegos/sucursal/101/equipo/{item_id}", data={**self.result(serial), "foto_antes": (io.BytesIO(PNG), f"{item_id}-antes.png"), "foto_despues": (io.BytesIO(PNG), f"{item_id}-despues.png")}, content_type="multipart/form-data")
            self.assertEqual(response.status_code, 302)
        done = self.client.post("/proveedor/matafuegos/sucursal/101/finalizar", data={"_csrf_token": "csrf", "remito": (io.BytesIO(PDF), "remito.pdf"), "certificado": (io.BytesIO(PDF), "certificado.pdf"), "documentos": (io.BytesIO(PDF), "anexo.pdf")}, content_type="multipart/form-data")
        self.assertEqual(done.status_code, 302); self.assertEqual(self.visits()[0]["estado"], "Realizado")
        visit = self.visits()[0]
        photo = visit["resultados"]["eq-101-a"]["fotos_antes"][0]["archivo"]
        file_response = self.client.get(f"/proveedor/matafuegos/visita/{visit['id']}/archivo/{photo}")
        self.assertEqual(file_response.status_code, 200); file_response.close()

        self.admin()
        returned = self.client.post("/admin/proveedores/matafuegos/sucursal/101/devolver", data={"_csrf_token": "csrf", "observacion": "Corregir ubicación"})
        self.assertEqual(returned.status_code, 302); self.assertEqual(self.visits()[0]["estado"], "Devuelto")
        self.provider()
        self.client.post("/proveedor/matafuegos/sucursal/101/equipo/eq-101-a", data=self.result("SER-101-A-NUEVA", ubicacion="Sala técnica"))
        self.client.post("/proveedor/matafuegos/sucursal/101/finalizar", data={"_csrf_token": "csrf"})
        self.admin()
        validated = self.client.post("/admin/proveedores/matafuegos/sucursal/101/validar", data={"_csrf_token": "csrf"})
        self.assertEqual(validated.status_code, 302); self.assertEqual(self.visits()[0]["estado"], "Validado")
        items = {item["id"]: item for item in tecman.load_matafuegos()["matafuegos"]}
        self.assertEqual(items["eq-101-a"]["nro_extintor"], "SER-101-A-NUEVA")
        self.assertEqual(items["eq-101-a"]["ubicacion"], "Sala técnica")
        self.assertEqual(items["eq-101-a"]["fecha_vencimiento_manual"], self.expiry)
        self.assertEqual(items["eq-101-a"]["historial_mantenimientos"][0]["visita_id"], visit["id"])
        actions = [entry["accion"] for entry in self.visits()[0]["historial"]]
        self.assertIn("Visita devuelta", actions); self.assertIn("Visita validada", actions)
        self.assertEqual(tickets_before, tecman.TICKETS_FILE.read_bytes())

    def test_no_finaliza_sin_todos_los_equipos_y_archivos_ajenos_se_rechazan(self):
        self.provider(); self.schedule()
        self.client.post("/proveedor/matafuegos/sucursal/101/equipo/eq-101-a", data=self.result("SER-A"))
        before = copy.deepcopy(self.visits())
        self.client.post("/proveedor/matafuegos/sucursal/101/finalizar", data={"_csrf_token": "csrf", "remito": (io.BytesIO(PDF), "remito.pdf"), "certificado": (io.BytesIO(PDF), "cert.pdf")}, content_type="multipart/form-data")
        self.assertEqual(before, self.visits())
        self.provider("proveedor_b", "Proveedor B")
        visit_id = self.visits()[0]["id"]
        self.assertEqual(self.client.get(f"/proveedor/matafuegos/visita/{visit_id}/archivo/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.pdf").status_code, 403)

    def test_persistencia_visitas_db_y_fallback_json(self):
        payload = {"visitas": [{"id": "VIS-DB", "sucursal_num": "101", "proveedor_key": "a", "estado": "Programado"}]}
        tecman.save_matafuegos_visitas(payload)
        self.assertEqual(tecman.load_matafuegos_visitas(), payload)
        with patch.object(tecman, "MatafuegoVisitaDB", object(), create=True), patch.object(tecman, "_db_list", return_value=payload["visitas"]) as db_list, patch.object(tecman, "_db_replace") as db_replace, patch.object(tecman, "_atomic_write") as atomic:
            tecman.USE_DB = True
            self.assertEqual(tecman.load_matafuegos_visitas(), payload)
            tecman.save_matafuegos_visitas(payload)
        db_list.assert_called_once(); db_replace.assert_called_once(); atomic.assert_called_once()


if __name__ == "__main__":
    unittest.main()
