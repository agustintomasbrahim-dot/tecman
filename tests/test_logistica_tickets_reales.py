import copy
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

_TMP = tempfile.TemporaryDirectory()
os.environ["TECMAN_DATA_DIR"] = str(Path(_TMP.name) / "data")
os.environ["TECMAN_UPLOADS_DIR"] = str(Path(_TMP.name) / "uploads")
os.environ.pop("DATABASE_URL", None)
os.environ["LOGISTICA_LOCAL_LOGIN_ENABLED"] = "false"
os.environ["LOGISTICA_PORTAL_TEST_MODE"] = "false"

import app as tecman  # noqa: E402
from logistica import LogisticsError, non_productive_catalog, project_purchase_ticket, validate_purchase_lines  # noqa: E402


class NonProductivePurchaseFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.original_paths = (tecman.TICKETS_FILE, tecman.STOCK_FILE, tecman.STOCK_MOV_FILE, tecman.UPLOADS_DIR)
        tecman.TICKETS_FILE = root / "tickets.json"
        tecman.STOCK_FILE = root / "stock.json"
        tecman.STOCK_MOV_FILE = root / "stock_movimientos.json"
        tecman.UPLOADS_DIR = root / "uploads"; tecman.UPLOADS_DIR.mkdir()
        tecman.app.config.update(TESTING=True, LOGISTICA_LOCAL_LOGIN_ENABLED=False,
                                 LOGISTICA_PORTAL_TEST_MODE=False, LOGISTICA_SMTP_MOCK=True)
        self.client = tecman.app.test_client()
        tecman.save_tickets([]); tecman.save_stock({"central": {}, "sucursales": {}}); tecman.save_movimientos({"movimientos": []})
        self.skus = list(non_productive_catalog())

    def tearDown(self):
        tecman.TICKETS_FILE, tecman.STOCK_FILE, tecman.STOCK_MOV_FILE, tecman.UPLOADS_DIR = self.original_paths
        self.temp.cleanup()

    def branch_session(self, branch="Sucursal 011"):
        with self.client.session_transaction() as sess:
            sess.clear(); sess.update(suc_user="suc011", suc_nombre=branch, auth_provider="entra",
                                      entra_role="sucursal", _csrf_token="csrf-test")

    def logistics_session(self, **overrides):
        values = {"logistica_role": "dabra", "logistica_user": tecman.PREPARADOR_DABRA_EMAIL,
                  "logistica_name": tecman.PREPARADOR_DABRA_NAME, "auth_provider": "entra",
                  "entra_role": "logistica", "_csrf_token": "csrf-test"}
        values.update(overrides)
        with self.client.session_transaction() as sess:
            sess.clear(); sess.update(values)

    def post(self, url, data=None):
        payload = {"_csrf_token": "csrf-test"}; payload.update(data or {})
        return self.client.post(url, data=payload)

    def create_ticket(self, quantities=(2, 1)):
        self.branch_session()
        data = {"categoria": "Compras no productivas", "subcategoria": "Insumos",
                "descripcion": "Reposición mensual", "solicitante_nombre": "Ana",
                "solicitante_apellido": "Sucursal", "zona_afectada": "Administración",
                "compra_np_sku[]": self.skus[:len(quantities)],
                "compra_np_cantidad[]": [str(x) for x in quantities]}
        response = self.client.post("/nuevo", data=data)
        self.assertEqual(response.status_code, 200)
        return tecman._load_tickets_raw()[0]

    def set_stock(self, values):
        stock = {"central": {}, "sucursales": {}}
        for sku, qty in values.items():
            stock["central"][sku] = {"cantidad": qty, "precio_unitario": 0}
        tecman.save_stock(stock)

    def test_e2e_multirenglon_descuenta_solo_al_confirmar_preparado(self):
        ticket = self.create_ticket()
        self.assertEqual(ticket["compra_np_estado"], "Recibido")
        self.assertEqual(ticket["notas"][0]["tipo"], "compra_np_recepcion_automatica")
        branch_page = self.client.get(f"/estado/{ticket['id']}")
        self.assertIn(b"Recibido", branch_page.data)
        for forbidden in (b"Responder a administraci", b"Finalizar ticket"):
            self.assertNotIn(forbidden, branch_page.data)
        before_ticket = copy.deepcopy(tecman._load_tickets_raw()[0])
        self.assertEqual(self.post(f"/estado/{ticket['id']}/responder", {"respuesta": "comentario"}).status_code, 409)
        self.assertEqual(self.post(f"/estado/{ticket['id']}/finalizar", {"motivo": "cerrar"}).status_code, 409)
        self.assertEqual(tecman._load_tickets_raw()[0], before_ticket)
        self.branch_session("Sucursal 014")
        self.assertEqual(self.post(f"/estado/{ticket['id']}/responder", {"respuesta": "comentario"}).status_code, 403)
        self.assertEqual(self.post(f"/estado/{ticket['id']}/finalizar", {"motivo": "cerrar"}).status_code, 403)
        self.assertEqual(tecman._load_tickets_raw()[0], before_ticket)
        self.set_stock({self.skus[0]: 4, self.skus[1]: 3})
        before_stock = copy.deepcopy(tecman.load_stock())
        before_movements = copy.deepcopy(tecman.load_movimientos())
        self.logistics_session()
        inbox = self.client.get("/logistica/tickets")
        self.assertIn(b"Abrochadora", inbox.data)
        self.assertEqual(inbox.data.count(b"Tengo stock"), 1)
        self.assertNotIn(b"Derivar a Compras", inbox.data)
        self.assertNotIn(b"Pedido preparado", inbox.data)
        for forbidden in (b"Cuento con stock", b"Preparar pedido", b"Tomar ticket", b"Responder", b"En proceso", b"Cerrar", b"Resolver", b"reserva"):
            self.assertNotIn(forbidden, inbox.data)
        response = self.post(f"/logistica/tickets/{ticket['id']}/tengo-stock")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/logistica/tickets")
        preparing = tecman._load_tickets_raw()[0]
        self.assertEqual(preparing["compra_np_estado"], "En preparación")
        self.assertEqual(tecman.load_stock(), before_stock)
        self.assertEqual(tecman.load_movimientos(), before_movements)
        inbox = self.client.get("/logistica/tickets")
        self.assertIn(b"Pedido preparado", inbox.data)
        self.assertNotIn(b"Tengo stock", inbox.data)
        detail = self.client.get(f"/logistica/tickets/{ticket['id']}")
        self.assertIn(b"Historial", detail.data)
        self.assertNotIn(b"/pedido-preparado", detail.data)
        self.assertEqual(self.post(f"/logistica/tickets/{ticket['id']}/pedido-preparado").status_code, 302)
        stock = tecman.load_stock(); movements = tecman.load_movimientos()["movimientos"]
        self.assertEqual((tecman.get_central_qty(stock, self.skus[0]), tecman.get_central_qty(stock, self.skus[1])), (2, 2))
        self.assertEqual(len(movements), 2)
        snapshot = (copy.deepcopy(stock), copy.deepcopy(movements))
        self.assertEqual(self.post(f"/logistica/tickets/{ticket['id']}/pedido-preparado").status_code, 302)
        self.assertEqual((tecman.load_stock(), tecman.load_movimientos()["movimientos"]), snapshot)
        self.branch_session()
        tracking = self.client.get(f"/estado/{ticket['id']}")
        self.assertIn("Pedido preparado".encode(), tracking.data)
        self.assertIn("stock canónico".encode(), tracking.data)

    def test_faltantes_exactos_derivacion_email_e_idempotencia(self):
        ticket = self.create_ticket((5, 2)); self.set_stock({self.skus[0]: 3, self.skus[1]: 0})
        self.logistics_session()
        inbox = self.client.get("/logistica/tickets")
        self.assertEqual(inbox.data.count(b"Derivar a Compras"), 1)
        self.assertNotIn(b"Tengo stock", inbox.data)
        self.assertNotIn(b"Pedido preparado", inbox.data)
        self.assertEqual(self.post(f"/logistica/tickets/{ticket['id']}/derivar-compras").status_code, 302)
        saved = tecman._load_tickets_raw()[0]; req = saved["compra_np_requisicion"]
        self.assertEqual(req["lineas"], [{"sku": self.skus[0], "cantidad": 2}, {"sku": self.skus[1], "cantidad": 2}])
        self.assertIsNone(req["numero"]); self.assertEqual(req["email_estado"], "enviado")
        snapshot = copy.deepcopy(saved)
        self.assertEqual(self.post(f"/logistica/tickets/{ticket['id']}/derivar-compras").status_code, 302)
        self.assertEqual(tecman._load_tickets_raw()[0], snapshot)
        self.assertEqual(tecman.load_movimientos()["movimientos"], [])

    def test_stock_cambia_antes_de_preparado_bloquea_sin_mutar_y_habilita_compras(self):
        ticket = self.create_ticket((2,)); self.set_stock({self.skus[0]: 2}); self.logistics_session()
        self.post(f"/logistica/tickets/{ticket['id']}/tengo-stock")
        self.set_stock({self.skus[0]: 1})
        before = (Path(tecman.TICKETS_FILE).read_bytes(), Path(tecman.STOCK_FILE).read_bytes(), Path(tecman.STOCK_MOV_FILE).read_bytes())
        response = self.post(f"/logistica/tickets/{ticket['id']}/pedido-preparado")
        self.assertEqual(response.status_code, 409)
        self.assertEqual((Path(tecman.TICKETS_FILE).read_bytes(), Path(tecman.STOCK_FILE).read_bytes(), Path(tecman.STOCK_MOV_FILE).read_bytes()), before)
        inbox = self.client.get("/logistica/tickets")
        self.assertIn(b"Derivar a Compras", inbox.data)
        self.assertNotIn(b"Pedido preparado", inbox.data)

    def test_concurrencia_no_duplica_descuento_ni_deja_stock_negativo(self):
        ticket = self.create_ticket((2,)); self.set_stock({self.skus[0]: 2})
        tecman._logistica_purchase_operation(ticket["id"], "tengo-stock", "Dabra")
        results = []
        def run():
            try: results.append(tecman._logistica_purchase_operation(ticket["id"], "preparado", "Dabra"))
            except Exception as exc: results.append(exc)
        threads = [threading.Thread(target=run) for _ in range(2)]
        [t.start() for t in threads]; [t.join() for t in threads]
        self.assertEqual(tecman.get_central_qty(tecman.load_stock(), self.skus[0]), 0)
        self.assertEqual(len(tecman.load_movimientos()["movimientos"]), 1)

    def test_rollback_logico_si_falla_persistencia(self):
        ticket = self.create_ticket((1,)); self.set_stock({self.skus[0]: 1})
        tecman._logistica_purchase_operation(ticket["id"], "tengo-stock", "Dabra")
        before = tuple(path.read_bytes() for path in (tecman.TICKETS_FILE, tecman.STOCK_FILE, tecman.STOCK_MOV_FILE))
        original = tecman._atomic_write
        calls = {"n": 0}
        def fail_second(path, data):
            calls["n"] += 1
            if calls["n"] == 2: raise OSError("falla simulada")
            return original(path, data)
        with patch.object(tecman, "_atomic_write", side_effect=fail_second):
            with self.assertRaises(OSError):
                tecman._logistica_purchase_operation(ticket["id"], "preparado", "Dabra")
        self.assertEqual(tuple(path.read_bytes() for path in (tecman.TICKETS_FILE, tecman.STOCK_FILE, tecman.STOCK_MOV_FILE)), before)

    def test_falla_email_no_revierte_y_reintento_explicito_no_duplica(self):
        ticket = self.create_ticket((3,)); self.set_stock({self.skus[0]: 0}); self.logistics_session()
        tecman.app.config["LOGISTICA_SMTP_MOCK"] = False
        with patch.object(tecman, "_smtp_send", side_effect=RuntimeError("smtp caído")) as sender:
            self.post(f"/logistica/tickets/{ticket['id']}/derivar-compras")
        saved = tecman._load_tickets_raw()[0]
        self.assertEqual(saved["compra_np_estado"], "Derivado a Compras")
        self.assertEqual(saved["compra_np_requisicion"]["email_estado"], "fallido")
        with patch.object(tecman, "_smtp_send") as sender:
            self.post(f"/logistica/tickets/{ticket['id']}/reintentar-email")
            self.post(f"/logistica/tickets/{ticket['id']}/reintentar-email")
            sender.assert_called_once()
        saved = tecman._load_tickets_raw()[0]
        self.assertEqual(saved["compra_np_requisicion"]["email_intentos"], 2)
        self.assertEqual(saved["compra_np_requisicion"]["email_estado"], "enviado")

    def test_backend_db_simulado_bloquea_filas_y_confirma_en_una_transaccion(self):
        ticket = self.create_ticket((1,)); ticket_row = type("TicketRow", (), {})()
        ticket_row.payload = copy.deepcopy(ticket); ticket_row.estado = ticket["estado"]
        stock_row = type("StockRow", (), {})(); stock_row.value = {"central": {self.skus[0]: {"cantidad": 1, "precio_unitario": 0}}, "sucursales": {}}
        locks, added = [], []
        class Query:
            def __init__(self, row=None): self.row = row
            def filter_by(self, **kwargs): return self
            def with_for_update(self): locks.append(True); return self
            def first(self): return self.row
            def filter(self, *args): return self
            def all(self): return []
        class Field:
            def like(self, pattern): return pattern
        class TicketModel: query = Query(ticket_row)
        class ConfigModel:
            query = Query(stock_row)
            def __init__(self, key, value): self.key, self.value = key, value
        class MovementModel:
            id = Field(); query = Query()
            @classmethod
            def from_dict(cls, data): return copy.deepcopy(data)
        class Session:
            def __init__(self): self.commits = self.rollbacks = 0
            def add(self, value): added.append(value)
            def commit(self): self.commits += 1
            def rollback(self): self.rollbacks += 1
        fake_db = type("DB", (), {"session": Session()})()
        def fake_list(model): return [copy.deepcopy(x) for x in added if isinstance(x, dict)]
        patches = (patch.object(tecman, "USE_DB", True), patch.object(tecman, "TicketDB", TicketModel, create=True),
                   patch.object(tecman, "ConfigDB", ConfigModel, create=True), patch.object(tecman, "StockMovimientoDB", MovementModel, create=True),
                   patch.object(tecman, "db", fake_db, create=True), patch.object(tecman, "_db_list", side_effect=fake_list))
        for item in patches: item.start()
        try:
            tecman._logistica_purchase_transaction(ticket["id"], "tengo-stock", "Dabra")
            tecman._logistica_purchase_transaction(ticket["id"], "preparado", "Dabra")
        finally:
            for item in reversed(patches): item.stop()
        self.assertGreaterEqual(len(locks), 4)
        self.assertEqual(stock_row.value["central"], {})
        self.assertEqual(len(added), 1)
        self.assertEqual(fake_db.session.commits, 2)
        self.assertEqual(fake_db.session.rollbacks, 0)

    def test_backend_db_deriva_y_reclama_email_una_sola_vez(self):
        ticket = self.create_ticket((2,)); ticket_row = type("TicketRow", (), {})()
        ticket_row.payload = copy.deepcopy(ticket); ticket_row.estado = ticket["estado"]
        stock_row = type("StockRow", (), {})(); stock_row.value = {"central": {}, "sucursales": {}}
        locks = []
        class Query:
            def __init__(self, row=None): self.row = row
            def filter_by(self, **kwargs): return self
            def with_for_update(self): locks.append(True); return self
            def first(self): return self.row
            def all(self): return []
        class TicketModel: query = Query(ticket_row)
        class ConfigModel: query = Query(stock_row)
        class MovementModel: query = Query()
        class Session:
            def __init__(self): self.commits = self.rollbacks = 0
            def add(self, value): pass
            def commit(self): self.commits += 1
            def rollback(self): self.rollbacks += 1
        fake_db = type("DB", (), {"session": Session()})()
        patches = (patch.object(tecman, "USE_DB", True), patch.object(tecman, "TicketDB", TicketModel, create=True),
                   patch.object(tecman, "ConfigDB", ConfigModel, create=True), patch.object(tecman, "StockMovimientoDB", MovementModel, create=True),
                   patch.object(tecman, "db", fake_db, create=True), patch.object(tecman, "_db_list", return_value=[]),
                   patch.object(tecman, "_logistica_send_compras_email"))
        started = [item.start() for item in patches]
        sender = started[-1]
        try:
            tecman._logistica_purchase_operation(ticket["id"], "derivar", "Dabra")
            snapshot = copy.deepcopy(ticket_row.payload)
            tecman._logistica_purchase_operation(ticket["id"], "derivar", "Dabra")
        finally:
            for item in reversed(patches): item.stop()
        req = ticket_row.payload["compra_np_requisicion"]
        self.assertEqual(req["email_estado"], "enviado")
        self.assertEqual(req["email_intentos"], 1)
        self.assertEqual(ticket_row.payload, snapshot)
        self.assertEqual(sender.call_count, 1)
        self.assertGreaterEqual(len(locks), 4)
        self.assertEqual(fake_db.session.commits, 3)
        self.assertEqual(fake_db.session.rollbacks, 0)

    def test_validacion_cerrada_y_upload_invalido_no_mutan(self):
        with self.assertRaises(LogisticsError): validate_purchase_lines([self.skus[0], self.skus[0]], [1, 2])
        with self.assertRaises(LogisticsError): validate_purchase_lines(["inventado"], [1])
        self.branch_session(); before = list(tecman.UPLOADS_DIR.iterdir())
        response = self.client.post("/nuevo", data={"categoria": "Compras no productivas", "subcategoria": "Insumos",
            "descripcion": "x", "zona_afectada": "Caja", "solicitante_nombre": "A", "solicitante_apellido": "B",
            "compra_np_sku[]": ["inventado"], "compra_np_cantidad[]": ["1"]})
        self.assertEqual(response.status_code, 302); self.assertEqual(tecman._load_tickets_raw(), [])
        self.assertEqual(list(tecman.UPLOADS_DIR.iterdir()), before)

    def test_get_puro_historicos_compatibilidad_y_permisos_csrf(self):
        historical = {"id": 7, "sucursal": "Sucursal 011", "categoria": "Compras no productivas",
            "tipo": "compra_no_productiva", "subcategoria": "Librería", "descripcion": "legacy",
            "estado": "Nuevo", "creado": "2026-01-01T00:00:00", "actualizado": "2026-01-01T00:00:00"}
        compatible = dict(historical, id=8, compra_np_estado="Stock confirmado",
                          compra_np_lineas=[{"sku": self.skus[0], "cantidad": 1}])
        tecman.save_tickets([historical, compatible]); self.set_stock({self.skus[0]: 1})
        before = Path(tecman.TICKETS_FILE).read_bytes()
        self.logistics_session(); page = self.client.get("/logistica/tickets")
        self.assertIn(b"Requiere completar detalle", page.data)
        self.assertIn("En preparación".encode(), page.data)
        self.assertIn(b"Pedido preparado", page.data)
        self.assertNotIn(b"Stock confirmado", page.data)
        self.assertEqual(Path(tecman.TICKETS_FILE).read_bytes(), before)
        self.assertEqual(self.client.post("/logistica/tickets/7/tengo-stock").status_code, 400)
        self.assertEqual(self.post("/logistica/tickets/8/preparar").status_code, 404)
        self.assertEqual(self.post("/logistica/tickets/8/cuento-con-stock").status_code, 404)
        self.assertEqual(self.post("/logistica/tickets/8/pedido-preparado").status_code, 302)
        self.assertEqual(tecman._load_tickets_raw()[1]["compra_np_estado"], "Pedido preparado")
        self.logistics_session(logistica_role="garin", logistica_user="garin@grupodexter.com.ar")
        self.assertEqual(self.client.get("/logistica/tickets").status_code, 403)
        self.assertEqual(self.post("/logistica/tickets/8/pedido-preparado").status_code, 403)
        projected = project_purchase_ticket(historical, {"central": {}})
        self.assertEqual(projected["compra_np_estado"], "Recibido")
        self.assertTrue(projected["compra_np_requiere_detalle"]); self.assertNotIn("compra_np_lineas", historical)


if __name__ == "__main__": unittest.main()
