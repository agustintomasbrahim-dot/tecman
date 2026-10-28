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


class AdminSecurityGuardsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.original_paths = (
            tecman.STOCK_FILE,
            tecman.TRANSFERS_FILE,
            tecman.STOCK_MOV_FILE,
        )
        tecman.app.config.update(TESTING=True, SECRET_KEY="test-only")
        tecman.USE_DB = False
        tecman.STOCK_FILE = root / "stock.json"
        tecman.TRANSFERS_FILE = root / "transfers.json"
        tecman.STOCK_MOV_FILE = root / "stock_movimientos.json"
        tecman.save_stock({"central": {"Guantes": {"cantidad": 5, "precio_unitario": 0}}, "sucursales": {}})
        tecman.save_transfers([])
        tecman.save_movimientos({"movimientos": []})
        self.client = tecman.app.test_client()

    def tearDown(self):
        tecman.STOCK_FILE, tecman.TRANSFERS_FILE, tecman.STOCK_MOV_FILE = self.original_paths
        tecman.USE_DB = False
        self.temp.cleanup()

    def session(self, role):
        with self.client.session_transaction() as session:
            session.clear()
            session.update(
                user=f"{role}-test",
                nombre=f"{role.title()} Test",
                rol=role,
                _csrf_token="csrf-test",
            )

    def test_metricas_detalle_es_solo_para_admin(self):
        self.session("tecnico")
        self.assertEqual(self.client.get("/admin/metricas/tickets").status_code, 403)

        self.session("admin")
        with patch.object(tecman, "load_tickets", return_value=[]):
            self.assertEqual(self.client.get("/admin/metricas/tickets").status_code, 200)

    def test_transferencia_stock_requiere_csrf_y_conserva_acceso_tecnico(self):
        self.session("tecnico")
        payload = {"item": "Guantes", "cantidad": "2", "destino": "Sucursal 001"}

        rejected = self.client.post("/admin/stock/transfer", data=payload)
        self.assertEqual(rejected.status_code, 400)
        self.assertEqual(tecman.get_central_qty(tecman.load_stock(), "Guantes"), 5)

        accepted = self.client.post(
            "/admin/stock/transfer",
            data={**payload, "_csrf_token": "csrf-test"},
        )
        self.assertEqual(accepted.status_code, 302)
        stock = tecman.load_stock()
        self.assertEqual(tecman.get_central_qty(stock, "Guantes"), 3)
        self.assertEqual(stock["sucursales"]["Sucursal 001"]["Guantes"], 2)

    def test_altas_y_precios_de_stock_requieren_csrf(self):
        self.session("admin")
        self.assertEqual(
            self.client.post("/admin/stock/add", data={"item": "Barbijos", "cantidad": "1"}).status_code,
            400,
        )
        self.assertEqual(
            self.client.post("/admin/stock/precio", data={"item": "Guantes", "precio_unitario": "25"}).status_code,
            400,
        )
        stock = tecman.load_stock()
        self.assertNotIn("Barbijos", stock["central"])
        self.assertEqual(stock["central"]["Guantes"]["precio_unitario"], 0)


if __name__ == "__main__":
    unittest.main()
