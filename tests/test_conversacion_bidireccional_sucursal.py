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


class ConversacionBidireccionalSucursalTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        tecman.app.config.update(TESTING=True, SECRET_KEY="test-only")
        tecman.USE_DB = False
        tecman.TICKETS_FILE = root / "tickets.json"
        tecman.NOTIF_ADMIN_FILE = root / "notif_admin.json"
        self.own = {
            "id": 101001,
            "sucursal": "Sucursal 230",
            "sucursal_num": "230",
            "categoria": "Mantenimiento",
            "subcategoria": "Iluminación",
            "descripcion": "Falla intermitente",
            "prioridad": 2,
            "estado": "Pendiente",
            "asignado": "Carolina",
            "creado": "2026-09-30T08:00:00",
            "actualizado": "2026-09-30T09:00:00",
            "notas": [
                {"autor": "Carolina", "fecha": "2026-09-30T09:00:00", "texto": "Respuesta a sucursal: ¿Sigue fallando?"},
                {"autor": "Sucursal 230", "fecha": "2026-09-30T08:30:00", "texto": "Se cortó dos veces."},
            ],
        }
        self.other = dict(self.own, id=101002, sucursal="Sucursal 231", sucursal_num="231", notas=[])
        self.resolved = dict(self.own, id=101003, estado="Resuelto", fecha_cierre="2026-09-30T09:05:00", notas=[])
        self.closed = dict(self.own, id=101004, estado="Cerrado", fecha_cierre="2026-09-30T09:06:00", notas=[])
        tecman.save_tickets([self.own, self.other, self.resolved, self.closed])
        tecman.save_notif_admin({"notificaciones": []})
        self.client = tecman.app.test_client()
        self._branch_session()

    def tearDown(self):
        tecman.USE_DB = False
        self.temp.cleanup()

    def _branch_session(self, scope=None):
        with self.client.session_transaction() as session:
            session.clear()
            session["suc_user"] = "suc230"
            session["suc_nombre"] = "Sucursal 230"
            if scope is not None:
                session["suc_general"] = True
                session["suc_scope_nums"] = scope
            session["_csrf_token"] = "csrf-test"

    def _admin_session(self):
        with self.client.session_transaction() as session:
            session.clear()
            session["user"] = "admin-test"
            session["rol"] = "admin"
            session["nombre"] = "Carolina"
            session["_csrf_token"] = "csrf-test"

    def _office_session(self, sector="Deposito", sede="Garin"):
        with self.client.session_transaction() as session:
            session.clear()
            session["suc_user"] = "ltapia"
            session["suc_nombre"] = sede
            session["oficina_user"] = "ltapia"
            session["oficina_sede"] = sede
            session["oficina_sector"] = sector
            session["nombre"] = "Lujan Tapia"
            session["auth_provider"] = "entra"
            session["entra_role"] = "oficina"
            session["_csrf_token"] = "csrf-test"

    def _post(self, ticket_id=101001, text="Confirmamos que continúa.", key="reply-101001-a", csrf="csrf-test"):
        return self.client.post(
            f"/estado/{ticket_id}/responder",
            data={"_csrf_token": csrf, "respuesta": text, "idempotency_key": key},
        )

    def _snapshot(self):
        return copy.deepcopy(tecman.load_tickets(readonly=True)), copy.deepcopy(tecman.load_notif_admin())

    def test_conversacion_cronologica_canonica_con_roles_en_sucursal_y_admin(self):
        page = self.client.get("/estado/101001").get_data(as_text=True)
        self.assertIn("Conversación del ticket", page)
        self.assertLess(page.index("Se cortó dos veces."), page.index("¿Sigue fallando?"))
        self.assertIn("Sucursal · Sucursal 230", page)
        self.assertIn("Administración · Carolina", page)

        self._admin_session()
        admin = self.client.get("/admin/ticket/101001").get_data(as_text=True)
        self.assertIn("Conversación del ticket", admin)
        self.assertLess(admin.index("Se cortó dos veces."), admin.index("¿Sigue fallando?"))
        self.assertIn("Sucursal · Sucursal 230", admin)
        self.assertIn("Administración · Carolina", admin)

    def test_respuesta_propia_posterior_a_admin_persiste_avisa_y_es_visible(self):
        response = self._post(text="Sí, volvió a fallar a las 09:20.")
        self.assertEqual(response.status_code, 302)
        saved = next(t for t in tecman.load_tickets(readonly=True) if t["id"] == 101001)
        event = saved["notas"][-1]
        self.assertEqual(event["rol"], "sucursal")
        self.assertEqual(event["tipo"], "respuesta_sucursal")
        self.assertEqual(event["texto"], "Respuesta de sucursal: Sí, volvió a fallar a las 09:20.")
        self.assertEqual(event["idempotency_key"], "reply-101001-a")
        notices = tecman.load_notif_admin()["notificaciones"]
        self.assertEqual(len(notices), 1)
        self.assertEqual(notices[0]["evento_id"], event["evento_id"])
        self.assertEqual(notices[0]["link"], "/admin/ticket/101001")

        self._admin_session()
        page = self.client.get("/admin/ticket/101001").get_data(as_text=True)
        self.assertIn("Sí, volvió a fallar a las 09:20.", page)
        self.assertIn("Sucursal · Sucursal 230", page)

    def test_scope_id_manipulado_e_invalidos_no_mutan(self):
        self.assertEqual(self.client.get("/estado/101002").status_code, 403)
        for ticket_id, text, key, csrf, status in [
            (101002, "Intento cruzado", "cross", "csrf-test", 403),
            (101001, "válida", "bad-csrf", "incorrecto", 400),
            (101001, "   ", "empty", "csrf-test", 400),
            (101001, "x" * 2001, "long", "csrf-test", 400),
            (101001, "válida", "clave con espacios", "csrf-test", 400),
        ]:
            with self.subTest(ticket_id=ticket_id, status=status):
                before = self._snapshot()
                response = self._post(ticket_id, text, key, csrf)
                self.assertEqual(response.status_code, status)
                self.assertEqual(self._snapshot(), before)

    def test_xss_se_escapa_e_idempotencia_evitar_repetidos(self):
        payload = '<script>alert("x")</script> listo'
        first = self._post(text=payload, key="retry-key")
        second = self._post(text=payload, key="retry-key")
        self.assertEqual(first.status_code, 302)
        self.assertEqual(second.status_code, 302)
        saved = next(t for t in tecman.load_tickets(readonly=True) if t["id"] == 101001)
        events = [n for n in saved["notas"] if n.get("idempotency_key") == "retry-key"]
        self.assertEqual(len(events), 1)
        self.assertEqual(len(tecman.load_notif_admin()["notificaciones"]), 1)
        page = self.client.get("/estado/101001").get_data(as_text=True)
        self.assertIn("&lt;script&gt;alert", page)
        self.assertNotIn(payload, page)

    def test_fallo_de_aviso_conserva_respuesta_y_reintento_completa_sin_duplicar(self):
        with patch.object(tecman, "agregar_notif_admin", side_effect=OSError("sin buzón")):
            first = self._post(text="Respuesta guardada aunque falle el aviso.", key="notice-retry")
        self.assertEqual(first.status_code, 302)
        saved = next(t for t in tecman.load_tickets(readonly=True) if t["id"] == 101001)
        self.assertEqual(len([n for n in saved["notas"] if n.get("idempotency_key") == "notice-retry"]), 1)
        self.assertEqual(tecman.load_notif_admin()["notificaciones"], [])

        second = self._post(text="Respuesta guardada aunque falle el aviso.", key="notice-retry")
        self.assertEqual(second.status_code, 302)
        saved = next(t for t in tecman.load_tickets(readonly=True) if t["id"] == 101001)
        self.assertEqual(len([n for n in saved["notas"] if n.get("idempotency_key") == "notice-retry"]), 1)
        self.assertEqual(len(tecman.load_notif_admin()["notificaciones"]), 1)

    def test_resuelto_se_reabre_a_pendiente_y_cerrado_se_bloquea(self):
        response = self._post(101003, "El problema reapareció.", "reopen")
        self.assertEqual(response.status_code, 302)
        saved = next(t for t in tecman.load_tickets(readonly=True) if t["id"] == 101003)
        self.assertEqual(saved["estado"], "Pendiente")
        self.assertNotIn("fecha_cierre", saved)
        self.assertEqual(saved["reaperturas"][-1]["estado_anterior"], "Resuelto")
        self.assertEqual(saved["reaperturas"][-1]["estado_nuevo"], "Pendiente")
        self.assertEqual(saved["notas"][-1]["estado_anterior"], "Resuelto")

        before = self._snapshot()
        blocked = self._post(101004, "No debe entrar", "closed")
        self.assertEqual(blocked.status_code, 409)
        self.assertEqual(self._snapshot(), before)
        closed_page = self.client.get("/estado/101004").get_data(as_text=True)
        self.assertNotIn('action="/estado/101004/responder"', closed_page)

    def test_get_no_escribe_y_formulario_emite_clave_de_reintento(self):
        with patch.object(tecman, "save_tickets", side_effect=AssertionError("GET escribió tickets")), \
             patch.object(tecman, "save_notif_admin", side_effect=AssertionError("GET escribió avisos")):
            response = self.client.get("/estado/101001")
        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn('name="idempotency_key"', page)

        self._admin_session()
        with patch.object(tecman, "save_tickets", side_effect=AssertionError("GET admin escribió tickets")), \
             patch.object(tecman, "save_notif_admin", side_effect=AssertionError("GET admin escribió avisos")):
            admin_response = self.client.get("/admin/ticket/101001")
        self.assertEqual(admin_response.status_code, 200)

    def test_oficina_garin_responde_solo_ticket_de_su_sede_y_sector(self):
        tickets = tecman.load_tickets(readonly=True)
        office_ticket = {k: v for k, v in self.own.items() if k != "sucursal_num"}
        tickets.extend([
            dict(office_ticket, id=101005, sucursal="Garin", sector_oficina="Deposito", origen="oficina", notas=[]),
            dict(office_ticket, id=101006, sucursal="Garin", sector_oficina="Oficinas", origen="oficina", notas=[]),
            dict(office_ticket, id=101007, sucursal="Dabra Central", sector_oficina="Deposito", origen="oficina", notas=[]),
        ])
        tecman.save_tickets(tickets)
        self._office_session()

        page = self.client.get("/estado/101005").get_data(as_text=True)
        self.assertIn('action="/estado/101005/responder"', page)
        response = self._post(101005, "Continúa luego de la respuesta administrativa.", "office-reply")
        self.assertEqual(response.status_code, 302)
        saved = next(t for t in tecman.load_tickets(readonly=True) if t["id"] == 101005)
        self.assertEqual(saved["notas"][-1]["rol"], "sector")
        self.assertEqual(saved["notas"][-1]["autor"], "Lujan Tapia")
        self.assertEqual(saved["notas"][-1]["sector"], "Deposito")
        rendered = self.client.get("/estado/101005").get_data(as_text=True)
        self.assertIn("Deposito · Lujan Tapia", rendered)

        for ticket_id in (101006, 101007):
            self.assertEqual(self.client.get(f"/estado/{ticket_id}").status_code, 403)
            before = self._snapshot()
            denied = self._post(ticket_id, "Intento fuera de alcance", f"cross-{ticket_id}")
            self.assertEqual(denied.status_code, 403)
            self.assertEqual(self._snapshot(), before)

    def test_admin_responder_agrega_evento_canonico_con_csrf(self):
        self._admin_session()
        response = self.client.post(
            "/admin/ticket/101001",
            data={
                "_csrf_token": "csrf-test",
                "accion": "responder_suc",
                "motivo": "otra",
                "motivo_detalle": "Revisen la térmica del tablero.",
            },
        )
        self.assertEqual(response.status_code, 302)
        saved = next(t for t in tecman.load_tickets(readonly=True) if t["id"] == 101001)
        event = saved["notas"][-1]
        self.assertEqual(event["rol"], "administracion")
        self.assertEqual(event["tipo"], "respuesta_administracion")
        self.assertEqual(event["texto"], "Respuesta a sucursal: Revisen la térmica del tablero.")

        before = self._snapshot()
        bad = self.client.post(
            "/admin/ticket/101001",
            data={"_csrf_token": "malo", "accion": "responder_suc", "motivo": "otra", "motivo_detalle": "No"},
        )
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(self._snapshot(), before)


if __name__ == "__main__":
    unittest.main()
