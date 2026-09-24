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


class FinalizarTicketSucursalTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        tecman.app.config.update(TESTING=True, SECRET_KEY="test-only")
        tecman.USE_DB = False
        tecman.TICKETS_FILE = root / "tickets.json"
        tecman.NOTIF_ADMIN_FILE = root / "notif_admin.json"
        self.ticket = {
            "id": 100240,
            "sucursal": "Sucursal 036",
            "sucursal_num": "036",
            "categoria": "CEYH",
            "subcategoria": "Mantenimiento general",
            "descripcion": "Baldosas rotas en la vereda",
            "prioridad": 2,
            "estado": "Pendiente",
            "asignado": "Equipo Central",
            "creado": "2026-09-20T09:00:00",
            "actualizado": "2026-09-21T10:00:00",
            "fotos": ["evidencia.jpg"],
            "adjuntos": [{"archivo": "informe.pdf"}],
            "notas": [{
                "autor": "Sucursal 036",
                "fecha": "2026-09-21T10:00:00",
                "texto": "Respuesta de sucursal: el municipio confirmó la reparación.",
                "visibilidad": "sucursal",
            }],
        }
        self.other = dict(
            self.ticket,
            id=100241,
            sucursal="Sucursal 037",
            sucursal_num="037",
            notas=[],
            fotos=["otra.jpg"],
            adjuntos=[],
        )
        self.final = dict(self.ticket, id=100242, estado="Resuelto", notas=[])
        self.material = dict(
            self.ticket,
            id=100243,
            categoria="Materiales",
            tipo="materiales",
            notas=[],
        )
        self.derived = dict(
            self.ticket,
            id=100244,
            tipo="trabajo_proveedor",
            origen_ticket_id=100200,
            notas=[],
        )
        tecman.save_tickets([
            self.ticket,
            self.other,
            self.final,
            self.material,
            self.derived,
        ])
        tecman.save_notif_admin({"notificaciones": []})
        self.client = tecman.app.test_client()
        self._branch_session("Sucursal 036")

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

    def _post(self, ticket_id=100240, motivo="La ciudad reparó la vereda.", csrf="csrf-test"):
        return self.client.post(
            f"/estado/{ticket_id}/finalizar",
            data={"_csrf_token": csrf, "motivo": motivo},
        )

    def _saved(self):
        return tecman.load_tickets()

    def _snapshot(self):
        return copy.deepcopy(self._saved()), copy.deepcopy(tecman.load_notif_admin())

    def test_render_muestra_accion_motivo_confirmacion_y_layout_responsive(self):
        response = self.client.get("/estado/100240")
        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("Finalizar ticket", page)
        self.assertIn('action="/estado/100240/finalizar"', page)
        self.assertIn('name="motivo"', page)
        self.assertIn('required', page)
        self.assertIn('maxlength="2000"', page)
        self.assertIn('name="_csrf_token" value="csrf-test"', page)
        self.assertIn("¿Confirmás que el problema ya está resuelto", page)
        self.assertIn("width:100%", page)

    def test_ticket_propio_finaliza_con_estado_campos_historial_aviso_y_preserva_archivos(self):
        motivo = "La ciudad reparó la vereda; no intervino Mantenimiento."
        response = self._post(motivo=motivo)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/estado/100240")

        saved = next(item for item in self._saved() if item["id"] == 100240)
        self.assertEqual(saved["estado"], "Resuelto")
        self.assertIs(saved["resuelto_por_sucursal"], True)
        self.assertEqual(saved["resuelto_por_sucursal_actor"], "Sucursal 036")
        self.assertEqual(saved["resuelto_por_sucursal_motivo"], motivo)
        self.assertIn("T", saved["resuelto_por_sucursal_fecha"])
        self.assertEqual(saved["actualizado"], saved["resuelto_por_sucursal_fecha"])
        self.assertEqual(saved["fotos"], ["evidencia.jpg"])
        self.assertEqual(saved["adjuntos"], [{"archivo": "informe.pdf"}])
        self.assertEqual(saved["notas"][0], self.ticket["notas"][0])
        note = saved["notas"][-1]
        self.assertEqual(note["tipo"], "resuelto_por_sucursal")
        self.assertEqual(note["autor"], "Sucursal 036")
        self.assertIn(motivo, note["texto"])

        notifications = tecman.load_notif_admin()["notificaciones"]
        self.assertEqual(len(notifications), 1)
        notice = notifications[0]
        self.assertEqual(notice["tipo"], "resuelto_por_sucursal")
        self.assertEqual(notice["autor"], "Sucursal 036")
        self.assertEqual(notice["link"], "/admin/ticket/100240")
        self.assertIn("Sucursal 036", notice["detalle"])
        self.assertIn("#100240", notice["titulo"])
        self.assertIn(motivo, notice["detalle"])

        page = self.client.get(response.headers["Location"]).get_data(as_text=True)
        self.assertNotIn('action="/estado/100240/finalizar"', page)
        self.assertIn("Ticket finalizado por la sucursal", page)

    def test_guardas_login_csrf_motivo_scope_inexistente_y_final_no_mutan(self):
        cases = [
            (100241, "Motivo válido", "csrf-test", 403),
            (100240, "Motivo válido", "", 400),
            (100240, "   ", "csrf-test", 400),
            (100240, "x" * 2001, "csrf-test", 400),
            (999999, "Motivo válido", "csrf-test", 404),
            (100242, "Motivo válido", "csrf-test", 409),
        ]
        for ticket_id, motivo, csrf, status in cases:
            with self.subTest(ticket_id=ticket_id, motivo_len=len(motivo), csrf=bool(csrf)):
                before = self._snapshot()
                response = self._post(ticket_id=ticket_id, motivo=motivo, csrf=csrf)
                self.assertEqual(response.status_code, status)
                self.assertEqual(self._snapshot(), before)

        before = self._snapshot()
        with self.client.session_transaction() as session:
            session.clear()
            session["_csrf_token"] = "csrf-test"
        response = self._post()
        self.assertEqual(response.status_code, 302)
        self.assertIn("/sucursal/login", response.headers["Location"])
        self.assertEqual(self._snapshot(), before)

    def test_multicuenta_respeta_scope_exacto(self):
        self._branch_session("Supervisión AMBA", scope=["036"])
        allowed = self._post(motivo="Resuelto por personal de la sucursal")
        self.assertEqual(allowed.status_code, 302)
        saved = next(item for item in self._saved() if item["id"] == 100240)
        self.assertEqual(saved["resuelto_por_sucursal_actor"], "Supervisión AMBA")

        self._branch_session("Supervisión AMBA", scope=["036"])
        before = self._snapshot()
        denied = self._post(ticket_id=100241)
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(self._snapshot(), before)

        self._branch_session("Portal Sucursales")
        with self.client.session_transaction() as session:
            session["suc_general"] = True
        before = self._snapshot()
        no_scope = self._post(ticket_id=100243)
        self.assertEqual(no_scope.status_code, 403)
        self.assertEqual(self._snapshot(), before)

    def test_regla_general_incluye_materiales_y_derivados_visibles(self):
        for ticket_id in (100243, 100244):
            with self.subTest(ticket_id=ticket_id):
                response = self._post(ticket_id=ticket_id, motivo="La sucursal confirma que ya está resuelto.")
                self.assertEqual(response.status_code, 302)
                saved = next(item for item in self._saved() if item["id"] == ticket_id)
                self.assertEqual(saved["estado"], "Resuelto")
                self.assertTrue(saved["resuelto_por_sucursal"])

    def test_fallo_del_aviso_no_revierte_el_cierre(self):
        with patch.object(tecman, "agregar_notif_admin", side_effect=OSError("sin almacenamiento")):
            response = self._post(motivo="Resuelto aunque falle el aviso")
        self.assertEqual(response.status_code, 302)
        saved = next(item for item in self._saved() if item["id"] == 100240)
        self.assertEqual(saved["estado"], "Resuelto")
        self.assertEqual(saved["resuelto_por_sucursal_motivo"], "Resuelto aunque falle el aviso")
        self.assertEqual(tecman.load_notif_admin()["notificaciones"], [])

    def test_render_escapa_motivo_en_historial(self):
        payload = '<script>alert("x")</script> & vereda lista'
        self.assertEqual(self._post(motivo=payload).status_code, 302)
        page = self.client.get("/estado/100240").get_data(as_text=True)
        self.assertIn("&lt;script&gt;alert", page)
        self.assertNotIn('<script>alert("x")</script>', page)

    def test_persistencia_db_conserva_payload_y_aviso(self):
        tickets = [copy.deepcopy(self.ticket), copy.deepcopy(self.other)]
        notifications = {"notificaciones": []}
        ticket_model = object()
        notification_model = object()
        replaced = {}

        def db_list(model):
            if model is ticket_model:
                return copy.deepcopy(tickets)
            if model is notification_model:
                return copy.deepcopy(notifications["notificaciones"])
            raise AssertionError(f"Modelo inesperado: {model}")

        def db_replace(model, rows):
            replaced[model] = copy.deepcopy(rows)

        with patch.object(tecman, "TicketDB", ticket_model, create=True), \
             patch.object(tecman, "NotifAdminDB", notification_model, create=True), \
             patch.object(tecman, "_db_list", side_effect=db_list), \
             patch.object(tecman, "_db_replace", side_effect=db_replace), \
             patch.object(tecman, "_atomic_write") as atomic_write:
            tecman.USE_DB = True
            try:
                response = self._post(motivo="Resuelto y persistido en DB")
            finally:
                tecman.USE_DB = False

        self.assertEqual(response.status_code, 302)
        persisted = next(item for item in replaced[ticket_model] if item["id"] == 100240)
        self.assertEqual(persisted["estado"], "Resuelto")
        self.assertEqual(persisted["resuelto_por_sucursal_motivo"], "Resuelto y persistido en DB")
        self.assertEqual(replaced[notification_model][0]["tipo"], "resuelto_por_sucursal")
        atomic_write.assert_called()


if __name__ == "__main__":
    unittest.main()
