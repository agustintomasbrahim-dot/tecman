import importlib.util
import os
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def _load_app(tmp_path, *, environment="", role_access=False):
    env = os.environ.copy()
    env.pop("DATABASE_URL", None)
    env.update({
        "DEMO_PASSWORD": "staging-only-test",
        "TECMAN_BUILD_MARKER": "test-build",
        "TECMAN_ENVIRONMENT": environment,
        "TECMAN_DEMO_ROLE_ACCESS_ENABLED": "true" if role_access else "false",
        "TECMAN_DATA_DIR": str(tmp_path / "data"),
        "TECMAN_UPLOADS_DIR": str(tmp_path / "uploads"),
    })
    module_name = f"tecman_demo_password_test_{uuid.uuid4().hex}"
    with patch.dict(os.environ, env, clear=True):
        spec = importlib.util.spec_from_file_location(module_name, ROOT / "app.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
    return module


def _ticket(ticket_id, service):
    return {
        "id": ticket_id,
        "sucursal": "DEMO 001",
        "servicio": service,
        "asunto": f"Solicitud DEMO {service}",
        "categoria": "",
        "subcategoria": "",
        "descripcion": f"Ticket ficticio de {service}",
        "prioridad": 4,
        "estado": "Nuevo",
        "asignado": "",
        "fotos": [],
        "observaciones": "",
        "creado": "2026-10-29T10:00:00",
        "actualizado": "2026-10-29T10:00:00",
    }


def _open_demo_gate(client):
    response = client.post("/demo-login", data={"password": "staging-only-test"})
    if response.status_code != 302:
        raise AssertionError("La puerta DEMO no aceptó la clave de prueba")
    client.get("/")
    with client.session_transaction() as sess:
        return sess["_csrf_token"]


class DemoPasswordTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_staging_password_and_health(self):
        module = _load_app(self.root)
        module.app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
        client = module.app.test_client()

        response = client.get("/")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/demo-login"))

        health = client.get("/health")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.get_json(), {"status": "ok", "build": "test-build"})

        denied = client.post("/demo-login", data={"password": "wrong"})
        self.assertEqual(denied.status_code, 200)
        self.assertIn("Contraseña incorrecta", denied.get_data(as_text=True))

        accepted = client.post("/demo-login", data={"password": "staging-only-test"})
        self.assertEqual(accepted.status_code, 302)
        self.assertTrue(accepted.headers["Location"].endswith("/"))

        page = client.get("/")
        self.assertEqual(page.status_code, 200)
        self.assertNotIn("Gestionar únicamente la cola de Marketing", page.get_data(as_text=True))

    def test_role_cards_require_explicit_staging_configuration(self):
        module = _load_app(self.root, environment="production", role_access=True)
        module.app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
        client = module.app.test_client()
        accepted = client.post("/demo-login", data={"password": "staging-only-test"})
        self.assertEqual(accepted.status_code, 302)

        page = client.get("/").get_data(as_text=True)
        self.assertNotIn("Gestionar únicamente la cola de Marketing", page)
        self.assertNotIn("Gestionar únicamente la cola de IT", page)
        denied = client.post("/demo/rol/marketing", data={"_csrf_token": "not-used"})
        self.assertEqual(denied.status_code, 404)

    def test_demo_roles_enter_correct_queue_and_cannot_cross_services(self):
        module = _load_app(self.root, environment="staging", role_access=True)
        module.app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
        module.save_tickets([
            _ticket(101, "marketing"),
            _ticket(102, "it"),
            _ticket(103, "mantenimiento"),
        ])
        client = module.app.test_client()

        anonymous = client.post("/demo/rol/marketing")
        self.assertEqual(anonymous.status_code, 302)
        self.assertTrue(anonymous.headers["Location"].endswith("/demo-login"))

        csrf = _open_demo_gate(client)
        page = client.get("/").get_data(as_text=True)
        self.assertIn("Gestionar únicamente la cola de Marketing", page)
        self.assertIn("Gestionar únicamente la cola de IT", page)

        invalid_csrf = client.post("/demo/rol/marketing", data={"_csrf_token": "wrong"})
        self.assertEqual(invalid_csrf.status_code, 400)

        entered = client.post("/demo/rol/marketing", data={"_csrf_token": csrf})
        self.assertEqual(entered.status_code, 302)
        self.assertTrue(entered.headers["Location"].endswith("/admin"))
        with client.session_transaction() as sess:
            self.assertEqual(sess["rol"], "marketing")
            self.assertEqual(sess["auth_provider"], "demo")
            self.assertIs(sess["demo_authenticated"], True)

        panel = client.get("/admin?vista=tabla")
        body = panel.get_data(as_text=True)
        self.assertEqual(panel.status_code, 200)
        self.assertIn("Cola de Marketing", body)
        self.assertIn("Este perfil gestiona únicamente tickets del servicio Marketing", body)
        self.assertIn("Solicitud DEMO marketing", body)
        self.assertNotIn("Solicitud DEMO it", body)
        self.assertNotIn("Ticket ficticio de mantenimiento", body)
        self.assertEqual(client.get("/admin/ticket/101").status_code, 200)
        self.assertEqual(client.get("/admin/ticket/102").status_code, 403)
        self.assertEqual(client.get("/admin/ticket/103").status_code, 403)

        client = module.app.test_client()
        csrf = _open_demo_gate(client)
        entered = client.post("/demo/rol/it", data={"_csrf_token": csrf})
        self.assertEqual(entered.status_code, 302)
        panel = client.get("/admin?vista=tabla")
        body = panel.get_data(as_text=True)
        self.assertIn("Cola de IT", body)
        self.assertIn("Este perfil gestiona únicamente tickets del servicio IT", body)
        self.assertIn("Solicitud DEMO it", body)
        self.assertNotIn("Solicitud DEMO marketing", body)
        self.assertEqual(client.get("/admin/ticket/102").status_code, 200)
        self.assertEqual(client.get("/admin/ticket/101").status_code, 403)


if __name__ == "__main__":
    unittest.main()
