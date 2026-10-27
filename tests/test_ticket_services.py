import copy
import os
import tempfile
import unittest
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch


_TEST_ROOT = tempfile.TemporaryDirectory()
os.environ["TECMAN_DATA_DIR"] = str(Path(_TEST_ROOT.name) / "data")
os.environ["TECMAN_UPLOADS_DIR"] = str(Path(_TEST_ROOT.name) / "uploads")
os.environ.pop("DATABASE_URL", None)

import app as tecman  # noqa: E402
from models import TicketDB  # noqa: E402


class TicketServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.originals = (tecman.TICKETS_FILE, tecman.UPLOADS_DIR, tecman.USE_DB)
        tecman.TICKETS_FILE = root / "tickets.json"
        tecman.UPLOADS_DIR = root / "uploads"
        tecman.UPLOADS_DIR.mkdir(parents=True)
        tecman.USE_DB = False
        tecman.app.config.update(TESTING=True, SECRET_KEY="ticket-services-test")
        tecman.save_tickets([])
        self.client = tecman.app.test_client()
        self.branch_session()

    def tearDown(self):
        tecman.TICKETS_FILE, tecman.UPLOADS_DIR, tecman.USE_DB = self.originals
        self.temp.cleanup()

    def branch_session(self):
        with self.client.session_transaction() as sess:
            sess.clear()
            sess.update(
                suc_user="suc011",
                suc_nombre="Sucursal 011",
                auth_provider="entra",
                entra_role="sucursal",
                _csrf_token="csrf-test",
            )

    def staff_session(self, role):
        with self.client.session_transaction() as sess:
            sess.clear()
            sess.update(
                user=f"user-{role}",
                nombre=role.title(),
                rol=role,
                auth_provider="legacy",
                _csrf_token="csrf-test",
            )

    def post_simple(self, service, **overrides):
        data = {
            "_csrf_token": "csrf-test",
            "servicio": service,
            "asunto": f"Solicitud {service}",
            "descripcion": "Detalle suficiente para revisar la solicitud",
            "solicitante_nombre": "Ana",
            "solicitante_apellido": "Sucursal",
        }
        data.update(overrides)
        return self.client.post("/nuevo", data=data)

    @staticmethod
    def ticket(ticket_id, service=None):
        ticket = {
            "id": ticket_id,
            "sucursal": "Sucursal 011",
            "categoria": "Otro",
            "subcategoria": "Otro",
            "descripcion": f"Ticket {ticket_id}",
            "prioridad": 4,
            "estado": "Nuevo",
            "asignado": "",
            "fotos": [],
            "observaciones": "",
            "creado": "2026-10-26T12:00:00",
            "actualizado": "2026-10-26T12:00:00",
        }
        if service:
            ticket["servicio"] = service
            ticket["asunto"] = f"Asunto {service}"
            ticket["categoria"] = ""
            ticket["subcategoria"] = ""
        return ticket

    def test_legacy_sin_campo_es_mantenimiento_sin_mutacion(self):
        legacy = self.ticket(1)
        before = copy.deepcopy(legacy)
        self.assertEqual(tecman.ticket_service(legacy), "mantenimiento")
        self.assertEqual(legacy, before)
        tecman.save_tickets([legacy])
        raw_before = tecman.TICKETS_FILE.read_bytes()
        loaded = tecman.load_tickets(readonly=True)
        self.assertNotIn("servicio", loaded[0])
        self.assertEqual(tecman.ticket_service(loaded[0]), "mantenimiento")
        self.assertEqual(tecman.TICKETS_FILE.read_bytes(), raw_before)

    def test_altas_validas_persisten_servicio_y_jsonb_payload(self):
        for index, service in enumerate(tecman.TICKET_SERVICES, start=1):
            tecman.save_tickets([])
            self.branch_session()
            if service == "mantenimiento":
                response = self.client.post("/nuevo", data={
                    "_csrf_token": "csrf-test",
                    "servicio": service,
                    "categoria": "Otro",
                    "subcategoria": "Otro",
                    "descripcion": "Falla general",
                    "solicitante_nombre": "Ana",
                    "solicitante_apellido": "Sucursal",
                })
            else:
                response = self.post_simple(service)
            self.assertEqual(response.status_code, 200, service)
            saved = tecman._load_tickets_raw()[0]
            self.assertEqual(saved["servicio"], service)
            db_ticket = TicketDB.from_dict(copy.deepcopy(saved))
            self.assertEqual(db_ticket.payload["servicio"], service)
            self.assertEqual(db_ticket.to_dict()["servicio"], service)

    def test_rechaza_servicio_ausente_o_invalido_sin_mutar(self):
        before = tecman.TICKETS_FILE.read_bytes()
        for service in ("", "ventas", "Mantenimiento inventado"):
            self.branch_session()
            response = self.post_simple(service)
            self.assertEqual(response.status_code, 400)
            self.assertEqual(tecman.TICKETS_FILE.read_bytes(), before)

    def test_marketing_it_exigen_identidad_del_solicitante(self):
        before = tecman.TICKETS_FILE.read_bytes()
        for service in ("marketing", "it"):
            self.branch_session()
            response = self.post_simple(service, solicitante_nombre="", solicitante_apellido="")
            self.assertEqual(response.status_code, 400)
            self.assertEqual(tecman.TICKETS_FILE.read_bytes(), before)

    def test_autoasignacion_solo_se_ejecuta_para_mantenimiento(self):
        with patch.object(tecman, "auto_assign", wraps=tecman.auto_assign) as assign:
            self.assertEqual(self.post_simple("marketing").status_code, 200)
            self.assertEqual(tecman._load_tickets_raw()[0]["asignado"], "")
            assign.assert_not_called()

        tecman.save_tickets([])
        self.branch_session()
        with patch.object(tecman, "auto_assign", return_value="Responsable actual") as assign:
            response = self.client.post("/nuevo", data={
                "_csrf_token": "csrf-test",
                "servicio": "mantenimiento",
                "categoria": "Otro",
                "subcategoria": "Otro",
                "descripcion": "Falla general",
                "solicitante_nombre": "Ana",
                "solicitante_apellido": "Sucursal",
            })
            self.assertEqual(response.status_code, 200)
            assign.assert_called_once_with("Otro", "Sucursal 011", "Otro")
            self.assertEqual(tecman._load_tickets_raw()[0]["asignado"], "Responsable actual")

    def test_aislamiento_por_rol_y_admin_global(self):
        tickets = [self.ticket(1), self.ticket(2, "marketing"), self.ticket(3, "it")]
        tecman.save_tickets(tickets)

        self.staff_session("marketing")
        with patch.object(tecman, "sync_alertas_syh"):
            panel = self.client.get("/admin?vista=tabla")
        body = panel.get_data(as_text=True)
        self.assertEqual(panel.status_code, 200)
        self.assertIn("Asunto marketing", body)
        self.assertNotIn("Asunto it", body)
        self.assertEqual(self.client.get("/admin/ticket/2").status_code, 200)
        self.assertEqual(self.client.get("/admin/ticket/3").status_code, 403)
        self.assertEqual(self.client.get("/admin/ticket/1").status_code, 403)
        update = self.client.post("/admin/ticket/2", data={
            "estado": "En progreso",
            "prioridad": "4",
            "asignado": "Equipo Marketing",
            "observaciones": "Revisión iniciada",
        })
        self.assertEqual(update.status_code, 302)
        self.assertEqual(tecman.load_tickets(readonly=True)[1]["asignado"], "Equipo Marketing")
        snapshot = tecman.TICKETS_FILE.read_bytes()
        self.assertEqual(self.client.post("/admin/ticket/3", data={"estado": "Cerrado"}).status_code, 403)
        self.assertEqual(tecman.TICKETS_FILE.read_bytes(), snapshot)

        self.staff_session("it")
        self.assertEqual(self.client.get("/admin/ticket/3").status_code, 200)
        self.assertEqual(self.client.get("/admin/ticket/2").status_code, 403)

        self.staff_session("admin")
        with patch.object(tecman, "sync_alertas_syh"):
            admin_panel = self.client.get("/admin?vista=tabla").get_data(as_text=True)
        for expected in ("Mantenimiento", "Asunto marketing", "Asunto it"):
            self.assertIn(expected, admin_panel)
        for ticket_id in (1, 2, 3):
            self.assertEqual(self.client.get(f"/admin/ticket/{ticket_id}").status_code, 200)

    def test_plantillas_muestran_selector_y_servicio(self):
        new_form = self.client.get("/nuevo").get_data(as_text=True)
        self.assertIn('name="servicio" id="servicio" required', new_form)
        for service, label in tecman.TICKET_SERVICE_LABELS.items():
            self.assertIn(f'<option value="{service}"', new_form)
            self.assertIn(label, new_form)
        self.assertIn('id="simple-service-fields"', new_form)
        self.assertIn('name="asunto"', new_form)

        tecman.save_tickets([self.ticket(2, "marketing")])
        self.staff_session("marketing")
        with patch.object(tecman, "sync_alertas_syh"):
            panel = self.client.get("/admin?vista=tabla").get_data(as_text=True)
        detail = self.client.get("/admin/ticket/2").get_data(as_text=True)
        self.assertIn("Marketing", panel)
        self.assertIn("Servicio", detail)
        self.assertIn("Marketing", detail)

    def test_staging_bloquea_comunicaciones_externas_aunque_haya_secretos(self):
        env = os.environ.copy()
        env.update({
            "TECMAN_EXTERNAL_NOTIFICATIONS_ENABLED": "false",
            "SMTP_HOST": "smtp.invalid",
            "SMTP_USER": "staging-user",
            "SMTP_PASSWORD": "staging-secret",
            "MAIL_FROM": "staging@example.invalid",
            "TELEGRAM_BOT_TOKEN": "staging-token",
            "TELEGRAM_CHAT_ID": "staging-chat",
        })
        env.pop("DATABASE_URL", None)
        with tempfile.TemporaryDirectory() as directory:
            env["TECMAN_DATA_DIR"] = str(Path(directory) / "data")
            env["TECMAN_UPLOADS_DIR"] = str(Path(directory) / "uploads")
            result = subprocess.run(
                [sys.executable, "-c", (
                    "import app; "
                    "assert app.EXTERNAL_NOTIFICATIONS_ENABLED is False; "
                    "assert app._smtp_send('nobody@example.invalid', 'test', '<p>test</p>') is None; "
                    "assert app._telegram_notify('test') is None"
                )],
                cwd=Path(__file__).resolve().parents[1],
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
            )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)


if __name__ == "__main__":
    unittest.main()
