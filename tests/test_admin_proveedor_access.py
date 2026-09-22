import json
import os
import re
import tempfile
import unittest
from pathlib import Path


_TEST_ROOT = tempfile.TemporaryDirectory()
os.environ["TECMAN_DATA_DIR"] = str(Path(_TEST_ROOT.name) / "data")
os.environ["TECMAN_UPLOADS_DIR"] = str(Path(_TEST_ROOT.name) / "uploads")
os.environ.pop("DATABASE_URL", None)

import app as tecman  # noqa: E402


class AdminProveedorAccessTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.data = self.root / "data"
        self.data.mkdir()
        self.original_paths = (
            tecman.PROVEEDOR_USERS_FILE,
            tecman.USERS_FILE,
            tecman.AUTH_AUDIT_FILE,
        )
        tecman.PROVEEDOR_USERS_FILE = self.data / "proveedor_users.json"
        tecman.USERS_FILE = self.data / "users.json"
        tecman.AUTH_AUDIT_FILE = self.data / "auth_audit_events.json"
        tecman.USE_DB = False
        tecman.app.config.update(TESTING=True, SECRET_KEY="provider-access-test")
        self.client = tecman.app.test_client()

    def tearDown(self):
        (
            tecman.PROVEEDOR_USERS_FILE,
            tecman.USERS_FILE,
            tecman.AUTH_AUDIT_FILE,
        ) = self.original_paths
        self.temp.cleanup()

    def _admin_session(self):
        with self.client.session_transaction() as sess:
            sess.clear()
            sess["user"] = "admin-test"
            sess["nombre"] = "Admin Test"
            sess["rol"] = "admin"
            sess["_csrf_token"] = "csrf-test"

    def _post_create(self, proveedor, usuario, password="", follow=False, endpoint="usuarios"):
        path = "/admin/usuarios/proveedores" if endpoint == "usuarios" else "/admin/proveedores/acceso"
        return self.client.post(
            path,
            data={
                "_csrf_token": "csrf-test",
                "proveedor_nombre": proveedor,
                "usuario": usuario,
                "password": password,
            },
            follow_redirects=follow,
        )

    def _custom_users(self):
        if not tecman.PROVEEDOR_USERS_FILE.exists():
            return {}
        return json.loads(tecman.PROVEEDOR_USERS_FILE.read_text(encoding="utf-8"))["users"]

    def _provider_login(self, username, password):
        self.client.get("/proveedor/login")
        with self.client.session_transaction() as sess:
            csrf = sess["_csrf_token"]
        return self.client.post(
            "/proveedor/login",
            data={"_csrf_token": csrf, "usuario": username, "password": password},
        )

    def _entra_provider_session(self, **overrides):
        values = {
            "prov_user": "preview.admin",
            "prov_nombre": "Previsualización Microsoft",
            "prov_tipo_cuenta": "admin_total",
            "prov_full_access": True,
            "auth_provider": "entra",
            "entra_role": "proveedor",
        }
        values.update(overrides)
        with self.client.session_transaction() as sess:
            sess.clear()
            sess.update(values)

    def test_entra_full_access_funciona_sin_debilitar_sesiones_incompletas_o_revocadas(self):
        self._entra_provider_session()
        allowed = self.client.get("/proveedor")
        self.assertEqual(allowed.status_code, 200)
        self.assertIn("Portal de proveedor", allowed.get_data(as_text=True))

        incomplete_sessions = (
            {"prov_full_access": False},
            {"entra_role": "admin"},
            {"auth_provider": "local"},
        )
        for overrides in incomplete_sessions:
            with self.subTest(overrides=overrides):
                self._entra_provider_session(**overrides)
                denied = self.client.get("/proveedor")
                self.assertEqual(denied.status_code, 302)
                self.assertTrue(denied.headers["Location"].endswith("/proveedores/login"))
                with self.client.session_transaction() as sess:
                    self.assertNotIn("prov_user", sess)

        tecman.USERS_FILE.write_text(
            json.dumps({
                "users": [{
                    "id": "entra-preview-user",
                    "username": "preview.admin",
                    "email": "preview.admin@example.com",
                    "status": "disabled",
                    "session_version": 2,
                }]
            }),
            encoding="utf-8",
        )
        self._entra_provider_session(auth_user_id="entra-preview-user", auth_session_version=2)
        self.assertEqual(self.client.get("/proveedor").status_code, 302)

        users = tecman._load_users_json()
        users["users"][0]["status"] = "active"
        tecman._save_users_json(users)
        self._entra_provider_session(auth_user_id="entra-preview-user", auth_session_version=1)
        self.assertEqual(self.client.get("/proveedor").status_code, 302)
        self._entra_provider_session(auth_user_id="entra-preview-user", auth_session_version=2)
        self.assertEqual(self.client.get("/proveedor").status_code, 200)

    def test_alta_desde_usuarios_asigna_tipo_hash_login_y_alcance(self):
        self._admin_session()
        cases = (
            ("Martin Microglobal", "portal_normal", "proveedor", "ClaveNormal-2026"),
            ("Diprogom", "portal_mata", "matafuegos", "ClaveMata-2026"),
            ("Gerardo Goog", "portal_fumiga", "fumigacion", "ClaveFumiga-2026"),
            ("CEYH", "portal_abono", "abono_fijo", "ClaveAbono-2026"),
        )
        for proveedor, username, expected_type, password in cases:
            response = self._post_create(proveedor, username, password)
            self.assertEqual(response.status_code, 302)
            account = self._custom_users()[username]
            self.assertEqual(account["tipo_cuenta"], expected_type)
            self.assertEqual(account["proveedores"], [proveedor])
            self.assertEqual(account["status"], "active")
            self.assertNotIn("password", account)
            self.assertTrue(tecman._verify_password(password, account["password_hash"]))
            self.assertEqual(tecman._proveedor_nombres_usuario(username), [proveedor])

            login = self._provider_login(username, password)
            self.assertEqual(login.status_code, 302)
            self.assertTrue(login.headers["Location"].endswith("/proveedores") or login.headers["Location"].endswith("/proveedor"))
            with self.client.session_transaction() as sess:
                self.assertEqual(sess["prov_user"], username)
                self.assertNotIn("user", sess)
                self.assertEqual(sess["prov_tipo_cuenta"], expected_type)
            self._admin_session()

    def test_temporal_se_muestra_una_vez_y_password_explicita_no_se_filtra(self):
        self._admin_session()
        generated = self._post_create("Martin Microglobal", "temporal_seguro", follow=True)
        body = generated.get_data(as_text=True)
        match = re.search(r"Contraseña temporal \(mostrar una sola vez\): ([^.<]+)", body)
        self.assertIsNotNone(match)
        temporary_password = match.group(1).strip()
        self.assertGreaterEqual(len(temporary_password), 10)
        account = self._custom_users()["temporal_seguro"]
        self.assertTrue(tecman._verify_password(temporary_password, account["password_hash"]))
        self.assertNotIn(temporary_password, tecman.PROVEEDOR_USERS_FILE.read_text(encoding="utf-8"))
        self.assertNotIn(temporary_password, self.client.get("/admin/usuarios").get_data(as_text=True))

        explicit = "NoDebeFiltrarse-2026"
        response = self._post_create("Diprogom", "explicita_segura", explicit, follow=True)
        self.assertNotIn(explicit, response.get_data(as_text=True))
        self.assertNotIn(explicit, tecman.PROVEEDOR_USERS_FILE.read_text(encoding="utf-8"))
        self.assertNotIn(explicit, tecman.AUTH_AUDIT_FILE.read_text(encoding="utf-8"))
        self.assertTrue(tecman._verify_password(explicit, self._custom_users()["explicita_segura"]["password_hash"]))

    def test_validaciones_csrf_permisos_catalogo_reservados_duplicados_y_defaults(self):
        self._admin_session()
        missing_csrf = self.client.post(
            "/admin/usuarios/proveedores",
            data={"proveedor_nombre": "CEYH", "usuario": "sin_csrf", "password": "Password-2026"},
        )
        self.assertEqual(missing_csrf.status_code, 400)

        with self.client.session_transaction() as sess:
            sess.clear()
            sess["user"] = "tecnico-test"
            sess["rol"] = "tecnico"
            sess["_csrf_token"] = "csrf-test"
        forbidden = self._post_create("CEYH", "no_admin", "Password-2026")
        self.assertEqual(forbidden.status_code, 403)

        self._admin_session()
        rejected = (
            ("No existe", "catalogo_invalido"),
            ("CEYH", "agustin"),
            ("CEYH", "matafuegos_demo"),
            ("Personal Mto. (camionetas propias)", "interno_no_proveedor"),
            ("CEYH", "=formula"),
        )
        for proveedor, username in rejected:
            response = self._post_create(proveedor, username, "Password-2026", follow=True)
            self.assertNotIn(username, self._custom_users())
            self.assertEqual(response.status_code, 200)

        self._post_create("CEYH", "duplicado_seguro", "Password-2026")
        duplicate = self._post_create("Diprogom", "duplicado_seguro", "OtraPassword-2026", follow=True)
        self.assertIn("El usuario ya existe", duplicate.get_data(as_text=True))
        self.assertEqual(self._custom_users()["duplicado_seguro"]["nombre"], "CEYH")

        protected = self.client.post(
            "/admin/usuarios/proveedores/matafuegos_demo/accion",
            data={"_csrf_token": "csrf-test", "action": "disable"},
            follow_redirects=True,
        )
        self.assertIn("sólo lectura", protected.get_data(as_text=True))
        self.assertNotIn("matafuegos_demo", self._custom_users())
        self.assertEqual(tecman.load_proveedor_users()["diprogom"], tecman.DEFAULT_PROVEEDOR_USERS["diprogom"])

    def test_archivo_operativo_no_puede_sobrescribir_cuentas_default(self):
        tecman.PROVEEDOR_USERS_FILE.write_text(
            json.dumps({
                "users": {
                    "diprogom": {
                        "password_hash": tecman._hash_password("IntentoOverride-2026"),
                        "nombre": "Proveedor ajeno",
                        "tipo_cuenta": "proveedor",
                        "proveedores": ["Proveedor ajeno"],
                    },
                    "legacy_custom": {
                        "password_hash": tecman._hash_password("LegacyCustom-2026"),
                        "nombre": "Martin Microglobal",
                        "tipo_cuenta": "proveedor",
                        "proveedores": ["Martin Microglobal"],
                    },
                }
            }),
            encoding="utf-8",
        )
        users = tecman.load_proveedor_users()
        self.assertEqual(users["diprogom"], tecman.DEFAULT_PROVEEDOR_USERS["diprogom"])
        self.assertEqual(users["legacy_custom"]["status"], "active")
        self.assertEqual(users["legacy_custom"]["session_version"], 1)
        tecman.save_proveedor_users(users)
        stored = self._custom_users()
        self.assertNotIn("diprogom", stored)
        self.assertIn("legacy_custom", stored)

    def test_endpoint_anterior_usa_helper_y_exige_csrf(self):
        self._admin_session()
        no_csrf = self.client.post(
            "/admin/proveedores/acceso",
            data={"proveedor_nombre": "Gerardo Goog", "usuario": "viejo_sin_csrf", "password": "Password-2026"},
        )
        self.assertEqual(no_csrf.status_code, 400)
        response = self._post_create("Gerardo Goog", "endpoint_viejo", "Password-2026", endpoint="anterior")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self._custom_users()["endpoint_viejo"]["tipo_cuenta"], "fumigacion")
        events = json.loads(tecman.AUTH_AUDIT_FILE.read_text(encoding="utf-8"))["events"]
        self.assertEqual(events[-1]["event_type"], "provider_user_created")

    def test_deshabilitar_habilitar_reset_y_revocacion_de_sesion(self):
        self._admin_session()
        original_password = "PasswordOriginal-2026"
        self._post_create("Martin Microglobal", "gestion_prov", original_password)
        login = self._provider_login("gestion_prov", original_password)
        self.assertEqual(login.status_code, 302)
        with self.client.session_transaction() as sess:
            old_version = sess["prov_session_version"]

        self._admin_session()
        disabled = self.client.post(
            "/admin/usuarios/proveedores/gestion_prov/accion",
            data={"_csrf_token": "csrf-test", "action": "disable"},
        )
        self.assertEqual(disabled.status_code, 302)
        account = self._custom_users()["gestion_prov"]
        self.assertEqual(account["status"], "disabled")
        self.assertGreater(account["session_version"], old_version)
        with self.client.session_transaction() as sess:
            sess.clear()
            sess["prov_user"] = "gestion_prov"
            sess["prov_nombre"] = "Martin Microglobal"
            sess["prov_tipo_cuenta"] = "proveedor"
            sess["prov_session_version"] = old_version
        blocked_upload = self.client.get("/static/uploads/archivo-protegido.pdf")
        self.assertEqual(blocked_upload.status_code, 403)
        with self.client.session_transaction() as sess:
            sess.clear()
            sess["prov_user"] = "gestion_prov"
            sess["prov_nombre"] = "Martin Microglobal"
            sess["prov_tipo_cuenta"] = "proveedor"
            sess["prov_session_version"] = old_version
        revoked = self.client.get("/proveedor")
        self.assertEqual(revoked.status_code, 302)
        self.assertTrue(revoked.headers["Location"].endswith("/proveedores/login"))
        denied = self._provider_login("gestion_prov", original_password)
        self.assertEqual(denied.status_code, 200)

        self._admin_session()
        self.client.post(
            "/admin/usuarios/proveedores/gestion_prov/accion",
            data={"_csrf_token": "csrf-test", "action": "enable"},
        )
        self.assertEqual(self._provider_login("gestion_prov", original_password).status_code, 302)
        with self.client.session_transaction() as sess:
            pre_reset_version = sess["prov_session_version"]

        self._admin_session()
        reset = self.client.post(
            "/admin/usuarios/proveedores/gestion_prov/accion",
            data={"_csrf_token": "csrf-test", "action": "reset_password"},
            follow_redirects=True,
        )
        match = re.search(r"Contraseña temporal para gestion_prov \(mostrar una sola vez\): ([^.<]+)", reset.get_data(as_text=True))
        self.assertIsNotNone(match)
        temporary_password = match.group(1).strip()
        account = self._custom_users()["gestion_prov"]
        self.assertNotIn("password", account)
        self.assertGreater(account["session_version"], pre_reset_version)
        self.assertNotEqual(account["password_hash"], tecman._hash_password(original_password))
        with self.client.session_transaction() as sess:
            sess.clear()
            sess["prov_user"] = "gestion_prov"
            sess["prov_nombre"] = "Martin Microglobal"
            sess["prov_tipo_cuenta"] = "proveedor"
            sess["prov_session_version"] = pre_reset_version
        self.assertEqual(self.client.get("/proveedor").status_code, 302)
        self.assertEqual(self._provider_login("gestion_prov", original_password).status_code, 200)
        self.assertEqual(self._provider_login("gestion_prov", temporary_password).status_code, 302)

        events_text = tecman.AUTH_AUDIT_FILE.read_text(encoding="utf-8")
        self.assertNotIn(temporary_password, events_text)
        for event in ("provider_user_disabled", "provider_user_enabled", "provider_temporary_password_generated"):
            self.assertIn(event, events_text)

    def test_ui_separa_dominios_y_alta_interna_predetermina_entra(self):
        self._admin_session()
        page = self.client.get("/admin/usuarios").get_data(as_text=True)
        self.assertIn("Personal y sucursales (Microsoft)", page)
        self.assertIn("Proveedores externos (usuario y contraseña)", page)
        self.assertIn("Personal y sucursales ingresan con Microsoft. Proveedores externos usan este usuario y contraseña", page)
        self.assertIn('<option value="entra" selected>Microsoft Entra (predeterminado)</option>', page)
        self.assertNotIn('name="password" type="text"', page)
        self.assertIn('type="password" name="password"', page)

        created = self.client.post(
            "/admin/usuarios",
            data={
                "_csrf_token": "csrf-test",
                "name": "Persona Microsoft",
                "email": "persona.microsoft@example.com",
                "role": "admin",
                "status": "active",
            },
        )
        self.assertEqual(created.status_code, 302)
        user = tecman._load_users_json()["users"][0]
        self.assertFalse(user.get("local_credentials"))
        self.assertEqual(user["auth_identities"][0]["provider"], "entra")


if __name__ == "__main__":
    unittest.main()
