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
from categories_data import MATERIAL_CATEGORIAS  # noqa: E402


PAUSED_CATEGORIES = ("Insumos Librería", "Insumos Limpieza")


class LibraryCleaningSuppliesFeatureFlagTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.originals = {
            "tickets": tecman.TICKETS_FILE,
            "uploads": tecman.UPLOADS_DIR,
            "use_db": tecman.USE_DB,
            "flag": tecman.app.config.get("ENABLE_LIBRARY_CLEANING_SUPPLIES"),
        }
        tecman.TICKETS_FILE = root / "tickets.json"
        tecman.UPLOADS_DIR = root / "uploads"
        tecman.UPLOADS_DIR.mkdir(parents=True)
        tecman.USE_DB = False
        tecman.app.config.update(
            TESTING=True,
            SECRET_KEY="library-cleaning-feature-flag-test",
            ENABLE_LIBRARY_CLEANING_SUPPLIES=False,
        )
        tecman.save_tickets([])
        self.client = tecman.app.test_client()
        self.branch_session()

    def tearDown(self):
        tecman.TICKETS_FILE = self.originals["tickets"]
        tecman.UPLOADS_DIR = self.originals["uploads"]
        tecman.USE_DB = self.originals["use_db"]
        tecman.app.config["ENABLE_LIBRARY_CLEANING_SUPPLIES"] = self.originals["flag"]
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

    def admin_session(self):
        with self.client.session_transaction() as session:
            session.clear()
            session.update(
                user="admin",
                nombre="Administración",
                rol="admin",
                _csrf_token="csrf-test",
            )

    def material_payload(self, categoria_mat, subitem_mat, **overrides):
        payload = {
            "_csrf_token": "csrf-test",
            "categoria": "Materiales",
            "subcategoria": "Solicitud de materiales",
            "categoria_mat": categoria_mat,
            "subitem_mat": subitem_mat,
            "cantidad_mat": "2",
            "zona_afectada": "Depósito",
            "descripcion": "Reposición operativa",
            "solicitante_nombre": "Ana",
            "solicitante_apellido": "Sucursal",
        }
        payload.update(overrides)
        return payload

    @staticmethod
    def historical_ticket():
        return {
            "id": 77,
            "sucursal": "Sucursal 011",
            "categoria": "Materiales",
            "subcategoria": "Solicitud de materiales",
            "categoria_mat": "Insumos Limpieza",
            "subitem_mat": "Balde",
            "cantidad_mat": "2",
            "tipo": "materiales",
            "descripcion": "Pedido histórico de limpieza",
            "estado": "Nuevo",
            "asignado": tecman.RESPONSABLE_MATERIALES,
            "creado": "2026-01-01T00:00:00",
            "actualizado": "2026-01-01T00:00:00",
        }

    def test_catalogo_canonico_permanece_completo_y_default_off(self):
        self.assertFalse(tecman._library_cleaning_supplies_enabled())
        catalogo = {categoria["nombre"]: categoria["items"] for categoria in MATERIAL_CATEGORIAS}
        for nombre in PAUSED_CATEGORIES:
            self.assertIn(nombre, catalogo)
            self.assertIsNotNone(tecman._material_catalog_item(nombre, catalogo[nombre][0]))

    def test_flag_off_oculta_ambas_categorias_en_nueva_carga(self):
        response = self.client.get("/nuevo?categoria=Materiales")
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("Solicitud de materiales", body)
        self.assertIn("Luminaria", body)
        for nombre in PAUSED_CATEGORIES:
            self.assertNotIn(nombre, body)
        self.assertEqual(
            self.client.get("/api/categorias?categoria=Materiales").get_json(),
            ["Solicitud de materiales"],
        )

    def test_flag_off_rechaza_ambas_categorias_antes_de_leer_o_mutar(self):
        historical = self.historical_ticket()
        tecman.save_tickets([historical])
        before_tickets = tecman.TICKETS_FILE.read_bytes()
        before_uploads = list(tecman.UPLOADS_DIR.iterdir())
        subitems = {
            categoria["nombre"]: categoria["items"][0]
            for categoria in MATERIAL_CATEGORIAS
            if categoria["nombre"] in PAUSED_CATEGORIES
        }

        no_csrf = self.material_payload("Insumos Limpieza", subitems["Insumos Limpieza"])
        no_csrf.pop("_csrf_token")
        with patch.object(tecman, "load_tickets", side_effect=AssertionError("no debe leer tickets")):
            self.assertEqual(self.client.post("/nuevo", data=no_csrf).status_code, 400)
        self.assertEqual(tecman.TICKETS_FILE.read_bytes(), before_tickets)

        for categoria in PAUSED_CATEGORIES:
            with self.subTest(categoria=categoria), \
                 patch.object(tecman, "load_tickets", side_effect=AssertionError("no debe leer tickets")), \
                 patch.object(tecman, "save_tickets", side_effect=AssertionError("no debe guardar tickets")):
                response = self.client.post(
                    "/nuevo",
                    data=self.material_payload(categoria, subitems[categoria]),
                )
            self.assertEqual(response.status_code, 404)
            self.assertEqual(tecman.TICKETS_FILE.read_bytes(), before_tickets)
            self.assertEqual(list(tecman.UPLOADS_DIR.iterdir()), before_uploads)

    def test_tipo_materiales_inyectado_se_rechaza_sin_mutar(self):
        before = tecman.TICKETS_FILE.read_bytes()
        response = self.client.post(
            "/nuevo",
            data=self.material_payload(
                "Insumos Limpieza",
                "Balde",
                categoria="Otro",
                subcategoria="Otro",
                tipo="materiales",
            ),
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(tecman.TICKETS_FILE.read_bytes(), before)

    def test_flag_on_muestra_y_crea_ambas_categorias(self):
        tecman.app.config["ENABLE_LIBRARY_CLEANING_SUPPLIES"] = True
        page = self.client.get("/nuevo?categoria=Materiales")
        body = page.get_data(as_text=True)
        for nombre in PAUSED_CATEGORIES:
            self.assertIn(nombre, body)

        subitems = {
            categoria["nombre"]: categoria["items"][0]
            for categoria in MATERIAL_CATEGORIAS
            if categoria["nombre"] in PAUSED_CATEGORIES
        }
        for index, categoria in enumerate(PAUSED_CATEGORIES, start=1):
            response = self.client.post(
                "/nuevo",
                data=self.material_payload(categoria, subitems[categoria]),
            )
            self.assertEqual(response.status_code, 200)
            saved = tecman._load_tickets_raw()
            self.assertEqual(saved[index - 1]["categoria_mat"], categoria)
            self.assertEqual(saved[index - 1]["subitem_mat"], subitems[categoria])

    def test_historico_sigue_visible_y_administrable_con_flag_off(self):
        historical = self.historical_ticket()
        tecman.save_tickets([historical])
        before = tecman.TICKETS_FILE.read_bytes()

        tracking = self.client.get("/estado/77")
        self.assertEqual(tracking.status_code, 200)
        self.assertIn("Insumos Limpieza", tracking.get_data(as_text=True))
        self.assertEqual(tecman.TICKETS_FILE.read_bytes(), before)

        self.admin_session()
        detail = self.client.get("/admin/pedido/77")
        self.assertEqual(detail.status_code, 200)
        self.assertIn("Insumos Limpieza", detail.get_data(as_text=True))
        self.assertEqual(tecman.TICKETS_FILE.read_bytes(), before)

    def test_complementos_y_stock_admin_conservan_catalogo_canonico(self):
        historical = self.historical_ticket()
        tecman.save_tickets([historical])
        before = copy.deepcopy(tecman._load_tickets_raw())
        self.admin_session()

        detail = self.client.get("/admin/pedido/77")
        stock = self.client.get("/admin/stock")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(stock.status_code, 200)
        for nombre in PAUSED_CATEGORIES:
            self.assertIn(nombre, detail.get_data(as_text=True))
            self.assertIn(nombre, stock.get_data(as_text=True))
        self.assertEqual(tecman._load_tickets_raw(), before)


if __name__ == "__main__":
    unittest.main()
