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
from logistica import non_productive_catalog  # noqa: E402


class NonProductivePurchaseFeatureFlagTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.originals = {
            "tickets": tecman.TICKETS_FILE,
            "stock": tecman.STOCK_FILE,
            "movements": tecman.STOCK_MOV_FILE,
            "uploads": tecman.UPLOADS_DIR,
            "use_db": tecman.USE_DB,
            "flag": tecman.app.config.get("ENABLE_NON_PRODUCTIVE_PURCHASES"),
        }
        tecman.TICKETS_FILE = root / "tickets.json"
        tecman.STOCK_FILE = root / "stock.json"
        tecman.STOCK_MOV_FILE = root / "stock_movimientos.json"
        tecman.UPLOADS_DIR = root / "uploads"
        tecman.UPLOADS_DIR.mkdir(parents=True)
        tecman.USE_DB = False
        tecman.app.config.update(
            TESTING=True,
            SECRET_KEY="feature-flag-test",
            ENABLE_NON_PRODUCTIVE_PURCHASES=False,
            LOGISTICA_SMTP_MOCK=True,
        )
        tecman.save_tickets([])
        tecman.save_stock({"central": {}, "sucursales": {}})
        tecman.save_movimientos({"movimientos": []})
        self.client = tecman.app.test_client()
        self.branch_session()
        self.sku = next(iter(non_productive_catalog()))

    def tearDown(self):
        tecman.TICKETS_FILE = self.originals["tickets"]
        tecman.STOCK_FILE = self.originals["stock"]
        tecman.STOCK_MOV_FILE = self.originals["movements"]
        tecman.UPLOADS_DIR = self.originals["uploads"]
        tecman.USE_DB = self.originals["use_db"]
        tecman.app.config["ENABLE_NON_PRODUCTIVE_PURCHASES"] = self.originals["flag"]
        self.temp.cleanup()

    def branch_session(self):
        with self.client.session_transaction() as session:
            session.clear()
            session.update(
                suc_user="suc011",
                suc_nombre="Sucursal 011",
                auth_provider="entra",
                entra_role="sucursal",
                _csrf_token="csrf-test",
            )

    def logistics_session(self, role="dabra"):
        with self.client.session_transaction() as session:
            session.clear()
            session.update(
                logistica_role=role,
                logistica_user=(
                    tecman.PREPARADOR_DABRA_EMAIL
                    if role == "dabra"
                    else "garin@grupodexter.com.ar"
                ),
                logistica_name="Logística",
                auth_provider="entra",
                entra_role="logistica",
                _csrf_token="csrf-test",
            )

    def purchase_payload(self, **overrides):
        payload = {
            "_csrf_token": "csrf-test",
            "categoria": "Compras no productivas",
            "subcategoria": "Insumos",
            "descripcion": "Reposición operativa",
            "solicitante_nombre": "Ana",
            "solicitante_apellido": "Sucursal",
            "zona_afectada": "Administración",
            "compra_np_sku[]": [self.sku],
            "compra_np_cantidad[]": ["2"],
        }
        payload.update(overrides)
        return payload

    @staticmethod
    def historical_ticket():
        return {
            "id": 77,
            "sucursal": "Sucursal 011",
            "categoria": "Compras no productivas",
            "tipo": "compra_no_productiva",
            "subcategoria": "Insumos",
            "descripcion": "Pedido histórico",
            "estado": "Nuevo",
            "compra_np_estado": "Recibido",
            "creado": "2026-01-01T00:00:00",
            "actualizado": "2026-01-01T00:00:00",
        }

    def test_flag_false_oculta_catalogo_y_conserva_nombres_reales(self):
        response = self.client.get("/nuevo?categoria=Compras%20no%20productivas")
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn(">Materiales</option>", body)
        self.assertIn(">Problema Eléctrico</option>", body)
        self.assertIn('name="_csrf_token" value="csrf-test"', body)
        self.assertNotIn("Compras no productivas", body)
        self.assertNotIn("compra_np_", body)
        self.assertEqual(
            self.client.get("/api/categorias?categoria=Compras%20no%20productivas").get_json(),
            [],
        )

    def test_post_manipulado_y_csrf_se_rechazan_sin_mutar_json_ni_db_simulada(self):
        tecman.save_tickets([self.historical_ticket()])
        before_tickets = tecman.TICKETS_FILE.read_bytes()
        before_uploads = list(tecman.UPLOADS_DIR.iterdir())

        no_csrf = self.purchase_payload()
        no_csrf.pop("_csrf_token")
        self.assertEqual(self.client.post("/nuevo", data=no_csrf).status_code, 400)
        self.assertEqual(tecman.TICKETS_FILE.read_bytes(), before_tickets)

        for payload in (
            self.purchase_payload(),
            self.purchase_payload(
                categoria="Otro",
                subcategoria="Otro",
                tipo="compra_no_productiva",
            ),
        ):
            with self.subTest(payload=payload):
                response = self.client.post("/nuevo", data=payload)
                self.assertEqual(response.status_code, 404)
                self.assertEqual(tecman.TICKETS_FILE.read_bytes(), before_tickets)
                self.assertEqual(list(tecman.UPLOADS_DIR.iterdir()), before_uploads)

        with patch.object(tecman, "USE_DB", True), \
             patch.object(tecman, "load_tickets", side_effect=AssertionError("no debe leer DB")), \
             patch.object(tecman, "save_tickets", side_effect=AssertionError("no debe escribir DB")):
            response = self.client.post("/nuevo", data=self.purchase_payload())
        self.assertEqual(response.status_code, 404)
        self.assertEqual(tecman.TICKETS_FILE.read_bytes(), before_tickets)

    def test_flag_true_muestra_y_crea_el_flujo_vigente(self):
        tecman.app.config["ENABLE_NON_PRODUCTIVE_PURCHASES"] = True
        page = self.client.get("/nuevo")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Compras no productivas", page.get_data(as_text=True))

        response = self.client.post("/nuevo", data=self.purchase_payload())
        self.assertEqual(response.status_code, 200)
        saved = tecman._load_tickets_raw()
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["tipo"], "compra_no_productiva")
        self.assertEqual(saved[0]["compra_np_lineas"], [{"sku": self.sku, "cantidad": 2}])

    def test_flag_false_preserva_historico_get_puro_y_roles_logistica(self):
        historical = self.historical_ticket()
        historical["compra_np_lineas"] = [{"sku": self.sku, "cantidad": 1}]
        tecman.save_tickets([historical])
        before = tecman.TICKETS_FILE.read_bytes()

        tracking = self.client.get("/estado/77")
        self.assertEqual(tracking.status_code, 200)
        self.assertIn("Pedido histórico", tracking.get_data(as_text=True))
        self.assertEqual(tecman.TICKETS_FILE.read_bytes(), before)

        self.logistics_session("dabra")
        inbox = self.client.get("/logistica/tickets")
        self.assertEqual(inbox.status_code, 200)
        self.assertIn(b"#77", inbox.data)
        self.assertIn("Abrochadora N° 50".encode(), inbox.data)
        self.assertEqual(tecman.TICKETS_FILE.read_bytes(), before)

        self.logistics_session("garin")
        self.assertEqual(self.client.get("/logistica/tickets").status_code, 403)
        self.assertEqual(tecman.TICKETS_FILE.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
