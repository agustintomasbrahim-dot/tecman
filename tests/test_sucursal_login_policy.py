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


class SucursalLoginPolicyTest(unittest.TestCase):
    def setUp(self):
        tecman.app.config.update(TESTING=True, SECRET_KEY="sucursal-login-policy-test")
        self.client = tecman.app.test_client()
        self.legacy_users = {
            "suc078": {"password": "LegacySucursal-2026", "sucursal": "Sucursal 078"}
        }

    def test_default_seguro_oculta_login_local_y_bloquea_post(self):
        self.assertFalse(tecman.SUCURSAL_LOCAL_LOGIN_ENABLED)
        with (
            patch.object(tecman, "SUCURSAL_LOCAL_LOGIN_ENABLED", False),
            patch.object(tecman, "SUCURSAL_USERS", self.legacy_users),
            patch.object(tecman, "_entra_is_configured", return_value=True),
        ):
            page = self.client.get("/sucursal/login")
            html = page.get_data(as_text=True)
            self.assertEqual(page.status_code, 200)
            self.assertIn("Ingreso habilitado por grupo de Microsoft", html)
            self.assertIn("Ingresar con Microsoft", html)
            self.assertIn('/auth/entra/start?portal=sucursal', html)
            self.assertNotIn('name="usuario"', html)
            self.assertNotIn('name="password"', html)

            blocked = self.client.post(
                "/sucursal/login",
                data={"usuario": "suc078", "password": "LegacySucursal-2026"},
            )
            self.assertEqual(blocked.status_code, 302)
            self.assertTrue(blocked.headers["Location"].endswith("/sucursal/login"))
            with self.client.session_transaction() as sess:
                self.assertNotIn("suc_user", sess)
                self.assertNotIn("suc_nombre", sess)

    def test_login_local_solo_funciona_con_flag_explicito(self):
        with (
            patch.object(tecman, "SUCURSAL_LOCAL_LOGIN_ENABLED", True),
            patch.object(tecman, "SUCURSAL_USERS", self.legacy_users),
            patch.object(tecman, "_entra_is_configured", return_value=True),
        ):
            page = self.client.get("/sucursal/login")
            html = page.get_data(as_text=True)
            self.assertIn('name="usuario"', html)
            self.assertIn('type="password" name="password"', html)
            self.assertIn("Ingresar con Microsoft", html)

            logged_in = self.client.post(
                "/sucursal/login",
                data={"usuario": "suc078", "password": "LegacySucursal-2026"},
            )
            self.assertEqual(logged_in.status_code, 302)
            with self.client.session_transaction() as sess:
                self.assertEqual(sess["suc_user"], "suc078")
                self.assertEqual(sess["suc_nombre"], "Sucursal 078")

    def test_inicio_microsoft_conserva_portal_sucursal(self):
        with (
            patch.object(tecman, "SUCURSAL_LOCAL_LOGIN_ENABLED", False),
            patch.object(tecman, "_entra_is_configured", return_value=True),
        ):
            response = self.client.get("/auth/entra/start?portal=sucursal")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/oauth2/v2.0/authorize?", response.headers["Location"])
        with self.client.session_transaction() as sess:
            self.assertEqual(sess["entra_requested_portal"], "sucursal")
            self.assertTrue(sess.get("entra_state"))
            self.assertTrue(sess.get("entra_nonce"))
            self.assertNotIn("suc_user", sess)


if __name__ == "__main__":
    unittest.main()
