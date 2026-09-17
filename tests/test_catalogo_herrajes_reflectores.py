import copy
import json
import os
import tempfile
import unittest
from pathlib import Path


_TEST_ROOT = tempfile.TemporaryDirectory()
os.environ["TECMAN_DATA_DIR"] = str(Path(_TEST_ROOT.name) / "data")
os.environ["TECMAN_UPLOADS_DIR"] = str(Path(_TEST_ROOT.name) / "uploads")
os.environ.pop("DATABASE_URL", None)

import app as tecman  # noqa: E402
from categories_data import MATERIAL_CATEGORIAS  # noqa: E402


REFLECTORES = [
    f"Reflector {potencia} W - Luz {temperatura}"
    for potencia in (30, 50, 100, 200)
    for temperatura in ("fría", "cálida")
]


class CatalogoHerrajesReflectoresTest(unittest.TestCase):
    TICKET_ID = 100500

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        tecman.app.config.update(TESTING=True, SECRET_KEY="test-only")
        tecman.USE_DB = False
        tecman.TICKETS_FILE = root / "tickets.json"
        tecman.STOCK_FILE = root / "stock.json"
        tecman.GUIAS_COUNTER_FILE = root / "guias_counter.json"
        tecman.UPLOADS_DIR = root / "uploads"
        tecman.UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
        tecman.save_tickets([])
        tecman.save_stock({"central": {}, "sucursales": {}})
        self.client = tecman.app.test_client()
        self._branch_session()

    def tearDown(self):
        tecman.USE_DB = False
        self.temp.cleanup()

    def _branch_session(self):
        with self.client.session_transaction() as session:
            session.clear()
            session["suc_user"] = "sucursal-test"
            session["suc_nombre"] = "Sucursal 142"
            session["_csrf_token"] = "csrf-test"

    def _admin_session(self):
        with self.client.session_transaction() as session:
            session.clear()
            session["user"] = "soria-test"
            session["nombre"] = "Soria Test"
            session["rol"] = "tecnico"
            session["_csrf_token"] = "csrf-test"

    def _material_form(self, categoria_mat, subitem_mat):
        return {
            "categoria": "Materiales",
            "subcategoria": "Solicitud de materiales",
            "descripcion": "Reposición para el salón",
            "solicitante_nombre": "Sucursal",
            "solicitante_apellido": "Test",
            "categoria_mat": categoria_mat,
            "subitem_mat": subitem_mat,
            "cantidad_mat": "2",
            "zona_afectada": "Salón principal",
        }

    def _pedido_existente(self):
        return {
            "id": self.TICKET_ID,
            "sucursal": "Sucursal 142",
            "categoria": "Materiales",
            "subcategoria": "Solicitud de materiales",
            "categoria_mat": "Luminaria",
            "subitem_mat": REFLECTORES[0],
            "cantidad_mat": "1",
            "descripcion": "Reposición",
            "estado": "Nuevo",
            "asignado": "Soria",
            "creado": "2026-09-17T08:00:00",
            "actualizado": "2026-09-17T08:00:00",
            "notas": [],
            "materiales_agregados": [],
            "materiales_a_comprar": [],
        }

    def test_catalogo_define_herrajes_y_ocho_reflectores_canonicos(self):
        catalogo = {categoria["nombre"]: categoria["items"] for categoria in MATERIAL_CATEGORIAS}
        self.assertEqual(catalogo["Herrajes"], ["Cerraduras", "Picaportes"])
        self.assertEqual([item for item in catalogo["Luminaria"] if item.startswith("Reflector ")], REFLECTORES)
        for item in REFLECTORES:
            self.assertEqual(tecman._material_catalog_item("Luminaria", item), f"Luminaria > {item}")
        self.assertEqual(tecman._material_catalog_item("Herrajes", "Cerraduras"), "Herrajes > Cerraduras")
        self.assertIsNone(tecman._material_catalog_item("Luminaria", "Reflector 100 W - Luz neutra"))

    def test_pedido_inicial_renderiza_herrajes_y_reflectores_como_opciones(self):
        response = self.client.get("/nuevo")
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn('<option value="Herrajes"', body)
        for item in ["Cerraduras", "Picaportes", *REFLECTORES]:
            self.assertIn(json.dumps(item), body)
        self.assertNotIn("Luz neutra", body)

    def test_selector_complementos_reutiliza_catalogo_aun_sin_stock(self):
        tecman.save_tickets([self._pedido_existente()])
        self._admin_session()
        response = self.client.get(f"/admin/pedido/{self.TICKET_ID}")
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn('<option value="Herrajes">Herrajes</option>', body)
        for item in ["Cerraduras", "Picaportes", *REFLECTORES]:
            self.assertIn(f'value="{item}"', body)
            self.assertIn(f"› {item} · Disponible: 0", body)

    def test_nuevas_claves_son_compatibles_con_stock_y_guia(self):
        tecman.save_tickets([self._pedido_existente()])
        tecman.save_stock({
            "central": {
                f"Luminaria > {REFLECTORES[0]}": {"cantidad": 1, "precio_unitario": 0},
                "Herrajes > Cerraduras": {"cantidad": 2, "precio_unitario": 0},
            },
            "sucursales": {},
        })
        self._admin_session()
        added = self.client.post(f"/admin/pedido/{self.TICKET_ID}", data={
            "_csrf_token": "csrf-test",
            "accion": "agregar_material_stock",
            "categoria_complemento": "Herrajes",
            "subitem_complemento": "Cerraduras",
            "cantidad_stock": "2",
        })
        self.assertEqual(added.status_code, 302)
        self.assertEqual(tecman.load_tickets()[0]["materiales_agregados"][0]["item"], "Herrajes > Cerraduras")

        confirmed = self.client.post(f"/admin/pedido/{self.TICKET_ID}", data={
            "_csrf_token": "csrf-test",
            "accion": "cuento_material",
            "metodo_envio": "Envio desde Central",
            "guia_carga_tipo": "Bultos",
            "guia_carga_cantidad": "1",
        })
        self.assertEqual(confirmed.status_code, 302)
        guide = self.client.get(f"/admin/pedido/{self.TICKET_ID}/guia")
        self.assertEqual(guide.status_code, 200)
        body = guide.get_data(as_text=True)
        self.assertIn(f"Luminaria - {REFLECTORES[0]}", body)
        self.assertIn("Herrajes &gt; Cerraduras", body)

    def test_backend_acepta_combinaciones_nuevas_y_rechaza_variantes_inventadas(self):
        for categoria, subitem in (("Luminaria", REFLECTORES[-1]), ("Herrajes", "Picaportes")):
            with self.subTest(categoria=categoria, subitem=subitem):
                tecman.save_tickets([])
                self._branch_session()
                response = self.client.post("/nuevo", data=self._material_form(categoria, subitem))
                self.assertEqual(response.status_code, 200)
                saved = tecman.load_tickets()
                self.assertEqual(len(saved), 1)
                self.assertEqual(saved[0]["categoria_mat"], categoria)
                self.assertEqual(saved[0]["subitem_mat"], subitem)

        tecman.save_tickets([])
        self._branch_session()
        response = self.client.post(
            "/nuevo",
            data=self._material_form("Luminaria", "Reflector 100 W - Luz neutra"),
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(tecman.load_tickets(), [])

        ticket = self._pedido_existente()
        tecman.save_tickets([ticket])
        tecman.save_stock({
            "central": {"Luminaria > Reflector 100 W - Luz neutra": {"cantidad": 10, "precio_unitario": 0}},
            "sucursales": {},
        })
        self._admin_session()
        before = copy.deepcopy(tecman.load_tickets())
        response = self.client.post(f"/admin/pedido/{self.TICKET_ID}", data={
            "_csrf_token": "csrf-test",
            "accion": "agregar_material_stock",
            "categoria_complemento": "Luminaria",
            "subitem_complemento": "Reflector 100 W - Luz neutra",
            "cantidad_stock": "1",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(tecman.load_tickets(), before)


if __name__ == "__main__":
    unittest.main()
