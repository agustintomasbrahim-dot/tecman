import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


_TEST_ROOT = tempfile.TemporaryDirectory()
os.environ["TECMAN_DATA_DIR"] = str(Path(_TEST_ROOT.name) / "data")
os.environ["TECMAN_UPLOADS_DIR"] = str(Path(_TEST_ROOT.name) / "uploads")
os.environ.pop("DATABASE_URL", None)

import app as tecman  # noqa: E402
from executive_report import rank_sucursal_logins  # noqa: E402


class SucursalLoginAuditTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.original_audit_file = tecman.AUTH_AUDIT_FILE
        tecman.app.config.update(TESTING=True, SECRET_KEY="sucursal-audit-test")
        tecman.USE_DB = False
        tecman.AUTH_AUDIT_FILE = Path(self.temp.name) / "auth_audit_events.json"
        tecman.AUTH_AUDIT_FILE.write_text('{"events": []}', encoding="utf-8")
        self.client = tecman.app.test_client()

    def tearDown(self):
        tecman.USE_DB = False
        tecman.AUTH_AUDIT_FILE = self.original_audit_file
        self.temp.cleanup()

    def events(self):
        return json.loads(tecman.AUTH_AUDIT_FILE.read_text(encoding="utf-8"))["events"]

    def entra_callback(self, identity, role, supervisor=None):
        msal_app = Mock()
        msal_app.acquire_token_by_authorization_code.return_value = {
            "id_token": "token-test",
            "access_token": "access-test",
        }
        with self.client.session_transaction() as sess:
            sess.clear()
            sess["entra_state"] = "state-test"
            sess["entra_nonce"] = "nonce-test"
            sess["entra_requested_portal"] = "supervisor" if role == "supervisor" else "sucursal"
        with (
            patch.object(tecman, "_entra_is_configured", return_value=True),
            patch.object(tecman, "_create_msal_app", return_value=msal_app),
            patch.object(tecman, "_validate_entra_id_token", return_value=identity),
            patch.object(tecman, "_entra_role_from_groups", return_value=role),
            patch.object(tecman, "_find_auth_user", return_value=None),
            patch.object(tecman, "_entra_configured_access_group_ids", return_value=set()),
            patch.object(tecman, "_supervisor_for_identity", return_value=supervisor),
        ):
            return self.client.get("/auth/entra/callback?state=state-test&code=code-test")

    def test_login_local_registra_una_sola_sucursal_canonica_sin_identidad(self):
        users = {"suc011": {"password": "secreto-test", "sucursal": "Sucursal 011"}}
        with (
            patch.object(tecman, "SUCURSAL_LOCAL_LOGIN_ENABLED", True),
            patch.object(tecman, "SUCURSAL_USERS", users),
        ):
            response = self.client.post(
                "/sucursal/login",
                data={"usuario": "suc011", "password": "secreto-test"},
            )
        self.assertEqual(response.status_code, 302)
        events = self.events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_type"], "login_success")
        self.assertEqual(events[0]["provider"], "local")
        self.assertEqual(events[0]["details"], {
            "role": "sucursal",
            "source": "local_credentials",
            "sucursal_num": "011",
            "sucursal_label": "Sucursal 011",
        })
        serialized = json.dumps(events).lower()
        self.assertNotIn("secreto-test", serialized)
        self.assertNotIn("suc011", serialized)

    def test_entra_identificable_registra_una_vez_y_sin_email_o_nombre(self):
        identity = {
            "object_id": "oid-011",
            "tenant_id": "tenant-test",
            "email": "suc011@example.invalid",
            "name": "Nombre Privado",
            "claims": {},
        }
        response = self.entra_callback(identity, "sucursal")
        self.assertEqual(response.status_code, 302)
        events = self.events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["provider"], "entra")
        self.assertEqual(events[0]["details"], {
            "role": "sucursal",
            "source": "branch_identity",
            "sucursal_num": "011",
            "sucursal_label": "Sucursal 011",
        })
        serialized = json.dumps(events).lower()
        self.assertNotIn("suc011@example.invalid", serialized)
        self.assertNotIn("nombre privado", serialized)

    def test_entra_general_y_supervisor_no_atribuyen_sucursal(self):
        general = {
            "object_id": "oid-general",
            "tenant_id": "tenant-test",
            "email": "general@example.invalid",
            "name": "Acceso General",
            "claims": {},
        }
        response = self.entra_callback(general, "sucursal")
        self.assertEqual(response.status_code, 302)
        supervisor = {
            "object_id": "oid-supervisor",
            "tenant_id": "tenant-test",
            "email": "supervisor@example.invalid",
            "name": "Persona Supervisora",
            "claims": {},
        }
        scope = {"nombre": "Zona", "sucursales": [{"num": "011"}, {"num": "014"}]}
        response = self.entra_callback(supervisor, "supervisor", supervisor=scope)
        self.assertEqual(response.status_code, 302)
        events = self.events()
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["details"], {"role": "sucursal", "source": "entra_group"})
        self.assertEqual(events[1]["details"], {"role": "supervisor", "source": "supervisor_scope"})
        self.assertTrue(all("sucursal_num" not in event["details"] for event in events))
        self.assertTrue(all("sucursal_label" not in event["details"] for event in events))

    def test_guard_evitar_doble_conteo_en_un_mismo_login(self):
        with tecman.app.test_request_context("/sucursal/login"):
            first = tecman._record_sucursal_login_success(
                "local", "sucursal", "local_credentials", suc_user="suc011", sucursal="Sucursal 011"
            )
            second = tecman._record_sucursal_login_success(
                "local", "sucursal", "local_credentials", suc_user="suc011", sucursal="Sucursal 011"
            )
        self.assertTrue(first)
        self.assertFalse(second)
        self.assertEqual(len(self.events()), 1)

    def test_postgresql_reutiliza_jsonb_existente_sin_migracion(self):
        added = []

        class FakeAuditEvent:
            def __init__(self, **values):
                self.__dict__.update(values)

        fake_db = SimpleNamespace(session=SimpleNamespace(
            add=lambda event: added.append(event),
            commit=Mock(),
        ))
        with (
            tecman.app.test_request_context("/auth/entra/callback"),
            patch.object(tecman, "USE_DB", True),
            patch.object(tecman, "db", fake_db, create=True),
            patch.object(tecman, "AuthAuditEventDB", FakeAuditEvent, create=True),
        ):
            tecman._record_sucursal_login_success(
                "entra", "sucursal", "branch_identity", suc_user="suc011", sucursal="Sucursal 011"
            )
        self.assertEqual(len(added), 1)
        self.assertEqual(added[0].event_type, "login_success")
        self.assertEqual(added[0].provider, "entra")
        self.assertEqual(added[0].details["sucursal_num"], "011")
        self.assertEqual(added[0].details["sucursal_label"], "Sucursal 011")
        fake_db.session.commit.assert_called_once_with()

    def test_ranking_puro_omite_generales_supervisores_y_eventos_no_canonicos(self):
        events = [
            {"event_type": "login_success", "details": {"role": "sucursal", "sucursal_num": "014", "sucursal_label": "Sucursal 014"}},
            {"event_type": "login_success", "details": {"role": "sucursal", "sucursal_num": "11", "sucursal_label": "Sucursal 011"}},
            {"event_type": "login_success", "details": {"role": "sucursal", "sucursal_num": "011", "sucursal_label": "Sucursal 011"}},
            {"event_type": "login_success", "details": {"role": "sucursal", "source": "entra_group"}},
            {"event_type": "login_success", "details": {"role": "supervisor", "source": "supervisor_scope"}},
            {"event_type": "login_failed", "details": {"role": "sucursal", "sucursal_num": "014", "sucursal_label": "Sucursal 014"}},
        ]
        before = json.dumps(events, sort_keys=True)
        self.assertEqual(rank_sucursal_logins(events), [
            {"sucursal_num": "011", "sucursal_label": "Sucursal 011", "ingresos": 2},
            {"sucursal_num": "014", "sucursal_label": "Sucursal 014", "ingresos": 1},
        ])
        self.assertEqual(json.dumps(events, sort_keys=True), before)


if __name__ == "__main__":
    unittest.main()
