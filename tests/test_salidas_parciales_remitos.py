import copy
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


class SalidasParcialesRemitosTest(unittest.TestCase):
    TICKET_ID = 100400

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.original_paths = (
            tecman.TICKETS_FILE,
            tecman.STOCK_FILE,
            tecman.STOCK_MOV_FILE,
            tecman.STOCK_LOTES_FILE,
            tecman.COMPROBANTES_FILE,
            tecman.GUIAS_COUNTER_FILE,
        )
        tecman.TICKETS_FILE = root / "tickets.json"
        tecman.STOCK_FILE = root / "stock.json"
        tecman.STOCK_MOV_FILE = root / "stock_movimientos.json"
        tecman.STOCK_LOTES_FILE = root / "stock_lotes.json"
        tecman.COMPROBANTES_FILE = root / "comprobantes.json"
        tecman.GUIAS_COUNTER_FILE = root / "guias_counter.json"
        tecman.USE_DB = False
        tecman.app.config.update(TESTING=True, SECRET_KEY="salidas-parciales-test")
        tecman.save_tickets([self._ticket()])
        tecman.save_stock({"central": {}, "sucursales": {}})
        tecman.save_movimientos({"movimientos": []})
        tecman.save_lotes_fifo({"lotes": []})
        tecman.save_comprobantes({"comprobantes": []})
        tecman._save_guias_counter({"ultimo": 400})
        self.client = tecman.app.test_client()
        with self.client.session_transaction() as session:
            session["user"] = "soria-test"
            session["nombre"] = "Soria Test"
            session["rol"] = "tecnico"
            session["_csrf_token"] = "csrf-test"

    def tearDown(self):
        (
            tecman.TICKETS_FILE,
            tecman.STOCK_FILE,
            tecman.STOCK_MOV_FILE,
            tecman.STOCK_LOTES_FILE,
            tecman.COMPROBANTES_FILE,
            tecman.GUIAS_COUNTER_FILE,
        ) = self.original_paths
        tecman.USE_DB = False
        self.temp.cleanup()

    def _ticket(self, **overrides):
        ticket = {
            "id": self.TICKET_ID,
            "sucursal": "Sucursal 142",
            "categoria": "Materiales",
            "subcategoria": "Solicitud de materiales",
            "descripcion": "Materiales para reparación",
            "estado": "Nuevo",
            "asignado": "Soria",
            "creado": "2026-09-23T10:00:00",
            "actualizado": "2026-09-23T10:00:00",
            "notas": [],
            "materiales_agregados": [],
            "materiales_a_comprar": [],
        }
        ticket.update(overrides)
        return ticket

    def _post_salida(self, items=None, **overrides):
        items = items if items is not None else [("Cable 2,5 mm", "3")]
        data = {
            "_csrf_token": "csrf-test",
            "accion": "crear_salida_parcial",
            "salida_material[]": [item[0] for item in items],
            "salida_cantidad[]": [item[1] for item in items],
            "salida_metodo": "Envio desde Central",
            "salida_destino": "Sucursal 142",
            "salida_carga_tipo": "Bultos",
            "salida_carga_cantidad": "2",
            "salida_observaciones": "Entrega parcial prioritaria",
        }
        data.update(overrides)
        return self.client.post(f"/admin/pedido/{self.TICKET_ID}", data=data)

    def _saved_ticket(self):
        return tecman.load_tickets()[0]

    def _runtime_snapshot(self):
        return {
            "ticket": copy.deepcopy(self._saved_ticket()),
            "stock": copy.deepcopy(tecman.load_stock()),
            "movimientos": copy.deepcopy(tecman.load_movimientos()),
            "lotes": copy.deepcopy(tecman.load_lotes_fifo()),
            "comprobantes": copy.deepcopy(tecman.load_comprobantes()),
            "counter": copy.deepcopy(tecman._load_guias_counter()),
        }

    def test_multiples_salidas_generan_numeros_y_comprobantes_distintos_sin_cerrar(self):
        stock_before = copy.deepcopy(tecman.load_stock())
        movimientos_before = copy.deepcopy(tecman.load_movimientos())
        lotes_before = copy.deepcopy(tecman.load_lotes_fifo())

        first = self._post_salida(items=[("Cable 2,5 mm", "3"), ("Caja estanca", "1")])
        self.assertEqual(first.status_code, 302)
        second = self._post_salida(
            items=[("Térmica 20 A", "2")],
            salida_metodo="Retira personal propio",
            salida_carga_tipo="Pallets",
            salida_carga_cantidad="1",
            salida_observaciones="Segunda entrega",
        )
        self.assertEqual(second.status_code, 302)

        ticket = self._saved_ticket()
        self.assertEqual(ticket["estado"], "En progreso")
        self.assertEqual(len(ticket["salidas_parciales"]), 2)
        first_output, second_output = ticket["salidas_parciales"]
        self.assertEqual(first_output["numero"], "0406-00000401")
        self.assertEqual(second_output["numero"], "0406-00000402")
        self.assertNotEqual(first_output["numero"], second_output["numero"])
        self.assertTrue(first_output["no_descuenta_stock"])
        self.assertEqual(first_output["items"][0], {"material": "Cable 2,5 mm", "cantidad": 3})
        self.assertEqual(second_output["carga_tipo"], "Pallets")

        comprobantes = tecman.load_comprobantes()["comprobantes"]
        self.assertEqual(len(comprobantes), 2)
        self.assertEqual({c["numero"] for c in comprobantes}, {"0406-00000401", "0406-00000402"})
        for output, comprobante in zip(ticket["salidas_parciales"], comprobantes):
            self.assertEqual(output["comprobante_id"], comprobante["id"])
            self.assertEqual(comprobante["tipo"], "remito_interno")
            self.assertEqual(comprobante["ticket_ids"], [self.TICKET_ID])
            self.assertTrue(comprobante["no_descuenta_stock"])

        self.assertEqual(tecman.load_stock(), stock_before)
        self.assertEqual(tecman.load_movimientos(), movimientos_before)
        self.assertEqual(tecman.load_lotes_fifo(), lotes_before)

    def test_historial_y_comprobante_imprimible_para_tecnico(self):
        self.assertEqual(self._post_salida().status_code, 302)
        ticket = self._saved_ticket()
        output = ticket["salidas_parciales"][0]

        page = self.client.get(f"/admin/pedido/{self.TICKET_ID}")
        self.assertEqual(page.status_code, 200)
        body = page.get_data(as_text=True)
        self.assertIn("Remitos emitidos (1)", body)
        self.assertIn(output["numero"], body)
        self.assertIn("Abrir / imprimir", body)
        self.assertIn("Sin descuento de stock", body)

        printed = self.client.get(f"/admin/comprobantes/{output['comprobante_id']}/imprimir")
        self.assertEqual(printed.status_code, 200)
        printed_body = printed.get_data(as_text=True)
        self.assertIn(output["numero"], printed_body)
        self.assertIn("Cable 2,5 mm", printed_body)
        self.assertIn("Envio desde Central", printed_body)
        self.assertIn("2 Bultos", printed_body)
        self.assertIn(f"/admin/pedido/{self.TICKET_ID}", printed_body)

    def test_rechazos_son_atomicos_y_no_avanzan_contador(self):
        invalid_cases = [
            {"_csrf_token": ""},
            {"salida_material[]": [], "salida_cantidad[]": []},
            {"salida_material[]": [""], "salida_cantidad[]": ["2"]},
            {"salida_cantidad[]": ["0"]},
            {"salida_cantidad[]": ["1.5"]},
            {"salida_cantidad[]": ["texto"]},
            {"salida_metodo": "Método inventado"},
            {"salida_destino": "Depósito inexistente"},
            {"salida_carga_tipo": "Camiones"},
            {"salida_carga_cantidad": "0"},
            {"salida_carga_cantidad": "1.5"},
        ]
        baseline = self._runtime_snapshot()
        for overrides in invalid_cases:
            with self.subTest(overrides=overrides):
                response = self._post_salida(**overrides)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(self._runtime_snapshot(), baseline)

    def test_ticket_finalizado_rechaza_sin_mutaciones(self):
        tecman.save_tickets([self._ticket(estado="Cerrado")])
        baseline = self._runtime_snapshot()
        response = self._post_salida()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self._runtime_snapshot(), baseline)

    def test_fallo_de_persistencia_revierte_ticket_comprobante_y_contador(self):
        baseline = self._runtime_snapshot()
        original_save = tecman.save_comprobantes
        llamadas = 0

        def fallar_primera_vez(data):
            nonlocal llamadas
            llamadas += 1
            if llamadas == 1:
                raise RuntimeError("fallo simulado")
            return original_save(data)

        with patch.object(tecman, "save_comprobantes", side_effect=fallar_primera_vez):
            with self.assertRaises(RuntimeError):
                self._post_salida()
        self.assertEqual(self._runtime_snapshot(), baseline)


if __name__ == "__main__":
    unittest.main()
