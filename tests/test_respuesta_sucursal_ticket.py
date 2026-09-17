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


class RespuestaSucursalTicketTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        tecman.app.config.update(TESTING=True, SECRET_KEY="test-only")
        tecman.USE_DB = False
        tecman.TICKETS_FILE = root / "tickets.json"
        tecman.NOTIF_ADMIN_FILE = root / "notif_admin.json"
        self.ticket = {
            "id": 100323,
            "sucursal": "Sucursal 230",
            "sucursal_num": "230",
            "categoria": "Mantenimiento",
            "subcategoria": "Iluminación",
            "descripcion": "Video reportado por la sucursal",
            "prioridad": 2,
            "estado": "Pendiente",
            "asignado": "Carolina",
            "creado": "2026-09-17T09:00:00",
            "actualizado": "2026-09-17T10:00:00",
            "notas": [{
                "autor": "Carolina",
                "fecha": "2026-09-17T10:00:00",
                "texto": "Respuesta a sucursal: Buenos días. ¿Podrían indicar si cuentan con todos los materiales necesarios?",
            }],
        }
        self.other = dict(self.ticket, id=100324, sucursal="Sucursal 231", sucursal_num="231", notas=[])
        tecman.save_tickets([self.ticket, self.other])
        tecman.save_notif_admin({"notificaciones": []})
        self.client = tecman.app.test_client()
        self._branch_session("Sucursal 230")

    def tearDown(self):
        tecman.USE_DB = False
        self.temp.cleanup()

    def _branch_session(self, label, scope=None):
        with self.client.session_transaction() as session:
            session.clear()
            session["suc_user"] = "sucursal-test"
            session["suc_nombre"] = label
            if scope is not None:
                session["suc_general"] = True
                session["suc_scope_nums"] = scope
            session["_csrf_token"] = "csrf-test"

    def _admin_session(self):
        with self.client.session_transaction() as session:
            session.clear()
            session["user"] = "admin-test"
            session["rol"] = "admin"
            session["nombre"] = "Agustín"
            session["_csrf_token"] = "csrf-test"

    def _post(self, ticket_id=100323, response_text="Sí, contamos con todos los materiales.", csrf="csrf-test"):
        return self.client.post(
            f"/estado/{ticket_id}/responder",
            data={"_csrf_token": csrf, "respuesta": response_text},
        )

    def _saved(self):
        return tecman.load_tickets()

    def test_formulario_visible_en_detalle_con_csrf_y_limite(self):
        response = self.client.get("/estado/100323")
        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("Responder a administración", page)
        self.assertIn('action="/estado/100323/responder"', page)
        self.assertIn('name="_csrf_token" value="csrf-test"', page)
        self.assertIn('name="respuesta"', page)
        self.assertIn('maxlength="2000"', page)

    def test_respuesta_valida_persiste_en_historial_avisa_y_vuelve_al_ticket(self):
        with patch.object(tecman, "_smtp_send") as smtp_send:
            response = self._post(response_text="Sí, tenemos lámparas y escalera.")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/estado/100323")
        smtp_send.assert_not_called()

        saved = next(item for item in self._saved() if item["id"] == 100323)
        self.assertEqual(saved["notas"][-1]["autor"], "Sucursal 230")
        self.assertEqual(saved["notas"][-1]["texto"], "Respuesta de sucursal: Sí, tenemos lámparas y escalera.")
        self.assertIn("T", saved["notas"][-1]["fecha"])
        self.assertEqual(saved["actualizado"], saved["notas"][-1]["fecha"])

        notifications = tecman.load_notif_admin()["notificaciones"]
        self.assertEqual(len(notifications), 1)
        self.assertEqual(notifications[0]["tipo"], "respuesta_sucursal")
        self.assertEqual(notifications[0]["autor"], "Sucursal 230")
        self.assertEqual(notifications[0]["link"], "/admin/ticket/100323")
        self.assertIn("#100323", notifications[0]["titulo"])
        self.assertIn("Sí, tenemos lámparas y escalera.", notifications[0]["detalle"])

        page = self.client.get(response.headers["Location"]).get_data(as_text=True)
        self.assertIn("Respuesta de sucursal: Sí, tenemos lámparas y escalera.", page)

    def test_ticket_ajeno_csrf_vacio_y_demasiado_largo_no_mutan(self):
        cases = [
            (100324, "Respuesta válida", "csrf-test", 403),
            (100323, "Respuesta válida", "", 400),
            (100323, "   ", "csrf-test", 400),
            (100323, "x" * 2001, "csrf-test", 400),
        ]
        for ticket_id, text, csrf, expected_status in cases:
            with self.subTest(ticket_id=ticket_id, size=len(text), csrf=bool(csrf)):
                before_tickets = copy.deepcopy(self._saved())
                before_notifications = copy.deepcopy(tecman.load_notif_admin())
                response = self._post(ticket_id=ticket_id, response_text=text, csrf=csrf)
                self.assertEqual(response.status_code, expected_status)
                self.assertEqual(self._saved(), before_tickets)
                self.assertEqual(tecman.load_notif_admin(), before_notifications)

    def test_supervisor_respeta_scope_exacto(self):
        self._branch_session("Supervisión NOA", scope=["230"])
        allowed = self._post(response_text="Respuesta del supervisor")
        self.assertEqual(allowed.status_code, 302)

        before = copy.deepcopy(self._saved())
        denied = self._post(ticket_id=100324, response_text="No debe guardarse")
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(self._saved(), before)

    def test_ruta_requiere_sesion_de_sucursal_y_scope_definido(self):
        before = copy.deepcopy(self._saved())
        with self.client.session_transaction() as session:
            session.clear()
            session["_csrf_token"] = "csrf-test"
        no_session = self._post()
        self.assertEqual(no_session.status_code, 302)
        self.assertIn("/login", no_session.headers["Location"])
        self.assertEqual(self._saved(), before)

        self._branch_session("Portal Sucursales")
        with self.client.session_transaction() as session:
            session["suc_general"] = True
        no_scope = self._post()
        self.assertEqual(no_scope.status_code, 403)
        self.assertEqual(self._saved(), before)

    def test_respuesta_es_visible_en_vista_administrativa_y_escapada(self):
        payload = '<script>alert("x")</script> & materiales listos'
        response = self._post(response_text=payload)
        self.assertEqual(response.status_code, 302)

        self._admin_session()
        admin_response = self.client.get("/admin/ticket/100323")
        self.assertEqual(admin_response.status_code, 200)
        page = admin_response.get_data(as_text=True)
        self.assertIn("Respuesta de sucursal:", page)
        self.assertIn("&lt;script&gt;alert", page)
        self.assertNotIn('<script>alert("x")</script>', page)
        self.assertIn("Sucursal 230", page)

    def test_persistencia_db_conserva_payload_y_aviso(self):
        tickets = [copy.deepcopy(self.ticket), copy.deepcopy(self.other)]
        notifications = {"notificaciones": []}

        def db_list(model):
            if model is tecman.TicketDB:
                return copy.deepcopy(tickets)
            if model is tecman.NotifAdminDB:
                return copy.deepcopy(notifications["notificaciones"])
            raise AssertionError(f"Modelo inesperado: {model}")

        replaced = {}

        def db_replace(model, rows):
            replaced[model] = copy.deepcopy(rows)

        ticket_model = object()
        notification_model = object()
        with patch.object(tecman, "TicketDB", ticket_model, create=True), \
             patch.object(tecman, "NotifAdminDB", notification_model, create=True), \
             patch.object(tecman, "_db_list", side_effect=db_list), \
             patch.object(tecman, "_db_replace", side_effect=db_replace), \
             patch.object(tecman, "_atomic_write") as atomic_write, \
             patch.object(tecman, "_smtp_send") as smtp_send:
            tecman.USE_DB = True
            try:
                response = self._post(response_text="Respuesta persistida en payload DB")
            finally:
                tecman.USE_DB = False

        self.assertEqual(response.status_code, 302)
        persisted = next(item for item in replaced[ticket_model] if item["id"] == 100323)
        self.assertEqual(persisted["notas"][-1]["texto"], "Respuesta de sucursal: Respuesta persistida en payload DB")
        self.assertEqual(replaced[notification_model][0]["tipo"], "respuesta_sucursal")
        atomic_write.assert_called()
        smtp_send.assert_not_called()


if __name__ == "__main__":
    unittest.main()
