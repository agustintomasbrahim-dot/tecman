import datetime
import json
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


class DailyAuditRegressionsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        tecman.app.config.update(TESTING=True, SECRET_KEY="daily-audit-test")
        tecman.USE_DB = False
        self.client = tecman.app.test_client()

    def tearDown(self):
        tecman.USE_DB = False
        self.temp.cleanup()

    def test_admin_login_syh_conserva_rol_y_abre_el_panel(self):
        admins = {
            "auditor": {
                "password": "test-password",
                "nombre": "Auditor",
                "rol": "admin",
            }
        }
        with patch.object(tecman, "ADMINS", admins), \
             patch.object(tecman, "SYH_USERS", {}), \
             patch.object(tecman, "load_syh", return_value={}):
            response = self.client.post(
                "/syh/login",
                data={"usuario": "auditor", "password": "test-password"},
            )
            self.assertEqual(response.status_code, 302)
            self.assertEqual(response.headers["Location"], "/syh")
            with self.client.session_transaction() as session:
                self.assertEqual(session["rol"], "admin")
                self.assertEqual(session["syh_user"], "auditor")
            panel = self.client.get("/syh")

        self.assertEqual(panel.status_code, 200)

    def test_login_syh_directo_limpia_una_sesion_de_otro_portal(self):
        with self.client.session_transaction() as session:
            session["user"] = "usuario-anterior"
            session["rol"] = "compras"
        syh_users = {"patricia": {"password": "test-password", "nombre": "Patricia"}}
        with patch.object(tecman, "SYH_USERS", syh_users), \
             patch.object(tecman, "load_syh", return_value={}):
            response = self.client.post(
                "/syh/login",
                data={"usuario": "patricia", "password": "test-password"},
            )
            self.assertEqual(response.status_code, 302)
            panel = self.client.get("/syh")

        self.assertEqual(panel.status_code, 200)
        with self.client.session_transaction() as session:
            self.assertNotIn("user", session)
            self.assertNotIn("rol", session)
            self.assertEqual(session["syh_user"], "patricia")

    def test_resumen_funciona_en_json_y_usa_fecha_creado(self):
        today = datetime.date.today().isoformat()
        dispatch_file = Path(self.temp.name) / "alertas_syh_dispatch.json"
        tickets = [
            {
                "id": 1,
                "sucursal": "Sucursal 001",
                "categoria": "Electricidad",
                "subcategoria": "Iluminación",
                "descripcion": "Prueba",
                "prioridad": 2,
                "estado": "Nuevo",
                "creado": f"{today}T04:00:00",
            },
            {
                "id": 2,
                "sucursal": "Sucursal 002",
                "categoria": "Plomería",
                "subcategoria": "Pérdida",
                "descripcion": "Prueba",
                "prioridad": 3,
                "estado": "Resuelto",
                "fecha_cierre": f"{today}T03:30:00",
                "creado": "2026-01-01T08:00:00",
            },
        ]
        alertas = {
            "alertas": [
                {
                    "id": "matafuego:001",
                    "sucursal_num": "001",
                    "estado": "Vencidos",
                    "tipos": "ABC",
                }
            ]
        }

        with patch.dict(os.environ, {"BACKUP_SECRET": "unit-secret"}), \
             patch.object(tecman, "ALERTAS_SYH_DISPATCH_FILE", dispatch_file), \
             patch.object(tecman, "load_tickets", return_value=tickets), \
             patch.object(tecman, "load_alertas_syh", return_value=alertas), \
             patch.object(tecman, "_telegram_notify") as telegram_notify, \
             patch.object(tecman, "_db_cfg_get", side_effect=AssertionError("JSON no debe consultar ConfigDB")):
            response = self.client.get("/api/resumen?token=unit-secret")
            second = self.client.get("/api/resumen?token=unit-secret")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(second.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["resueltos_hoy"], 1)
        self.assertEqual(len(payload["nuevos_ultimas_24h"]), 1)
        self.assertEqual(payload["nuevos_ultimas_24h"][0]["fecha"], today)
        telegram_notify.assert_called_once()
        dispatch = json.loads(dispatch_file.read_text(encoding="utf-8"))
        self.assertEqual(dispatch["telegram_notif_fecha"], today)


if __name__ == "__main__":
    unittest.main()
