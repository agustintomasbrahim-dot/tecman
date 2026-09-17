import copy
import os
import tempfile
import unittest
from pathlib import Path


_TEST_ROOT = tempfile.TemporaryDirectory()
os.environ["TECMAN_DATA_DIR"] = str(Path(_TEST_ROOT.name) / "data")
os.environ["TECMAN_UPLOADS_DIR"] = str(Path(_TEST_ROOT.name) / "uploads")
os.environ.pop("DATABASE_URL", None)

import app as tecman  # noqa: E402


class PedidoComplementosTest(unittest.TestCase):
    TICKET_ID = 100338
    PRINCIPAL = "Luminaria > Lámparas AR111"
    COMPLEMENTO = "Luminaria > Zócalos"

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        tecman.app.config.update(TESTING=True, SECRET_KEY="test-only")
        tecman.USE_DB = False
        tecman.TICKETS_FILE = root / "tickets.json"
        tecman.STOCK_FILE = root / "stock.json"
        tecman.GUIAS_COUNTER_FILE = root / "guias_counter.json"
        tecman.save_tickets([self._ticket()])
        tecman.save_stock({
            "central": {
                self.PRINCIPAL: {"cantidad": 12, "precio_unitario": 0},
                self.COMPLEMENTO: {"cantidad": 8, "precio_unitario": 0},
            },
            "sucursales": {},
        })
        self.client = tecman.app.test_client()
        with self.client.session_transaction() as session:
            session["user"] = "soria-test"
            session["nombre"] = "Soria Test"
            session["rol"] = "tecnico"
            session["_csrf_token"] = "csrf-test"

    def tearDown(self):
        self.temp.cleanup()

    def _ticket(self):
        return {
            "id": self.TICKET_ID,
            "sucursal": "Sucursal 142",
            "categoria": "Materiales",
            "subcategoria": "Solicitud de materiales",
            "categoria_mat": "Luminaria",
            "subitem_mat": "Lámparas AR111",
            "cantidad_mat": "12",
            "descripcion": "Reposición de luminarias",
            "estado": "Nuevo",
            "asignado": "Soria",
            "creado": "2026-09-17T08:00:00",
            "actualizado": "2026-09-17T08:00:00",
            "notas": [],
            "materiales_agregados": [],
            "materiales_a_comprar": [],
            "metodo_envio": "Envio desde Central",
        }

    def _saved_ticket(self):
        return tecman.load_tickets()[0]

    def _add_complement(self, **overrides):
        data = {
            "_csrf_token": "csrf-test",
            "accion": "agregar_material_stock",
            "categoria_complemento": "Luminaria",
            "subitem_complemento": "Zócalos",
            "cantidad_stock": "5",
            "detalle_stock": "Dicroica / GU10",
        }
        data.update(overrides)
        return self.client.post(f"/admin/pedido/{self.TICKET_ID}", data=data)

    def test_selector_se_puebla_desde_catalogo_y_muestra_stock(self):
        response = self.client.get(f"/admin/pedido/{self.TICKET_ID}")
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn('name="categoria_complemento"', body)
        self.assertIn('value="Luminaria"', body)
        self.assertIn('name="subitem_complemento"', body)
        self.assertIn('value="Zócalos"', body)
        self.assertIn("Disponible: 8", body)

    def test_complemento_valido_se_agrega_y_persiste(self):
        response = self._add_complement()
        self.assertEqual(response.status_code, 302)
        saved = self._saved_ticket()
        self.assertEqual(len(saved["materiales_agregados"]), 1)
        self.assertEqual(saved["materiales_agregados"][0]["item"], self.COMPLEMENTO)
        self.assertEqual(saved["materiales_agregados"][0]["cantidad"], 5)
        self.assertEqual(saved["materiales_agregados"][0]["detalle"], "Dicroica / GU10")
        self.assertEqual(saved["estado"], "Nuevo")

        second = self._add_complement(cantidad_stock="2", detalle_stock="Segundo complemento")
        self.assertEqual(second.status_code, 302)
        saved = self._saved_ticket()
        self.assertEqual(len(saved["materiales_agregados"]), 2)
        self.assertEqual([item["cantidad"] for item in saved["materiales_agregados"]], [5, 2])

        page = self.client.get(f"/admin/pedido/{self.TICKET_ID}").get_data(as_text=True)
        self.assertIn("Luminaria &gt; Zócalos", page)
        self.assertIn("x5", page)
        self.assertIn("x2", page)

    def test_guia_incluye_principal_y_complemento_con_cantidades(self):
        self._add_complement()
        confirmed = self.client.post(f"/admin/pedido/{self.TICKET_ID}", data={
            "_csrf_token": "csrf-test",
            "accion": "cuento_material",
            "metodo_envio": "Envio desde Central",
            "guia_carga_tipo": "Bultos",
            "guia_carga_cantidad": "1",
        })
        self.assertEqual(confirmed.status_code, 302)
        self.assertTrue(confirmed.headers["Location"].endswith(f"/admin/pedido/{self.TICKET_ID}/guia"))
        response = self.client.get(f"/admin/pedido/{self.TICKET_ID}/guia")
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("Luminaria - Lámparas AR111", body)
        self.assertIn("Luminaria &gt; Zócalos", body)
        self.assertRegex(body, r'<td class="cant">12</td>\s*<td>Luminaria - Lámparas AR111</td>')
        self.assertRegex(body, r'<td class="cant">5</td>\s*<td>Luminaria &gt; Zócalos — Dicroica / GU10</td>')

    def test_entradas_invalidas_y_csrf_no_modifican_el_ticket(self):
        before = copy.deepcopy(self._saved_ticket())
        invalid_cases = [
            {"_csrf_token": ""},
            {"categoria_complemento": "Luminaria", "subitem_complemento": "No existe"},
            {"cantidad_stock": "0"},
            {"cantidad_stock": "texto"},
            {"cantidad_stock": "99"},
        ]
        for overrides in invalid_cases:
            with self.subTest(overrides=overrides):
                response = self._add_complement(**overrides)
                self.assertIn(response.status_code, (302, 400))
                self.assertEqual(self._saved_ticket(), before)


if __name__ == "__main__":
    unittest.main()
