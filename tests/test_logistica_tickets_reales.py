import copy
import json
import os
import tempfile
import unittest
from pathlib import Path

# El aislamiento debe existir antes de importar app.
_TMP = tempfile.TemporaryDirectory()
os.environ["TECMAN_DATA_DIR"] = str(Path(_TMP.name) / "data")
os.environ["TECMAN_UPLOADS_DIR"] = str(Path(_TMP.name) / "uploads")
os.environ.pop("DATABASE_URL", None)
os.environ["LOGISTICA_LOCAL_LOGIN_ENABLED"] = "false"
os.environ["LOGISTICA_PORTAL_TEST_MODE"] = "false"

import app as tecman  # noqa: E402
from logistica import (  # noqa: E402
    LogisticsError,
    is_non_productive_purchase_ticket,
    mutate_purchase_ticket,
)


class RealLogisticsTicketFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.original_paths = (
            tecman.TICKETS_FILE,
            tecman.USERS_FILE,
            tecman.logistica_service.store.json_path,
        )
        tecman.TICKETS_FILE = root / "tickets.json"
        tecman.USERS_FILE = root / "users.json"
        tecman.logistica_service.store.json_path = root / "logistica_insumos.json"
        tecman.app.config.update(
            TESTING=True,
            LOGISTICA_LOCAL_LOGIN_ENABLED=False,
            LOGISTICA_PORTAL_TEST_MODE=False,
        )
        self.client = tecman.app.test_client()
        tecman.save_tickets([])
        tecman._save_users_json({"users": []})

    def tearDown(self):
        tecman.TICKETS_FILE, tecman.USERS_FILE, tecman.logistica_service.store.json_path = self.original_paths
        self.temp.cleanup()

    def branch_session(self, branch="Sucursal 011"):
        with self.client.session_transaction() as sess:
            sess.clear()
            sess.update(
                suc_user="suc011",
                suc_nombre=branch,
                auth_provider="entra",
                entra_role="sucursal",
                _csrf_token="csrf-test",
            )

    def logistics_session(self, **overrides):
        values = {
            "logistica_role": "dabra",
            "logistica_user": tecman.PREPARADOR_DABRA_EMAIL,
            "logistica_name": tecman.PREPARADOR_DABRA_NAME,
            "auth_provider": "entra",
            "entra_role": "logistica",
            "_csrf_token": "csrf-test",
        }
        values.update(overrides)
        with self.client.session_transaction() as sess:
            sess.clear()
            sess.update(values)

    def post(self, url, data=None):
        payload = {"_csrf_token": "csrf-test"}
        payload.update(data or {})
        return self.client.post(url, data=payload)

    def create_real_ticket(self):
        self.branch_session()
        response = self.client.post("/nuevo", data={
            "categoria": "Compras no productivas",
            "subcategoria": "Librería",
            "descripcion": "Resmas A4 para administración",
            "solicitante_nombre": "Ana",
            "solicitante_apellido": "Sucursal",
            "zona_afectada": "Administración",
            "compra_np_cantidad": "2 cajas",
            "compra_np_fecha_necesaria": "2026-10-05",
        })
        self.assertEqual(response.status_code, 200)
        ticket = tecman._load_tickets_raw()[0]
        self.assertEqual((ticket["categoria"], ticket["tipo"], ticket["subcategoria"]),
                         ("Compras no productivas", "compra_no_productiva", "Librería"))
        return ticket

    def test_flujo_completo_json_y_seguimiento_sucursal(self):
        ticket = self.create_real_ticket()
        ticket_id = ticket["id"]
        logistics_json = tecman.logistica_service.store.json_path
        logistics_before = logistics_json.read_bytes() if logistics_json.exists() else None

        self.logistics_session()
        inbox = self.client.get("/logistica/tickets")
        self.assertEqual(inbox.status_code, 200)
        self.assertIn(b"Librer", inbox.data)
        self.assertIn(b"Resmas A4", inbox.data)
        self.assertEqual(logistics_json.read_bytes() if logistics_json.exists() else None, logistics_before)

        self.assertEqual(self.post(f"/logistica/tickets/{ticket_id}/en-proceso").status_code, 302)
        after_start = copy.deepcopy(tecman._load_tickets_raw()[0])
        self.assertEqual(after_start["estado"], "En progreso")
        self.assertEqual(self.post(f"/logistica/tickets/{ticket_id}/en-proceso").status_code, 302)
        self.assertEqual(tecman._load_tickets_raw()[0], after_start)

        response_text = "Pedido recibido; estamos coordinando la compra."
        self.assertEqual(self.post(f"/logistica/tickets/{ticket_id}/responder", {"respuesta": response_text}).status_code, 302)
        after_response = copy.deepcopy(tecman._load_tickets_raw()[0])
        self.assertEqual(after_response["respuesta_logistica"], response_text)
        self.assertEqual(self.post(f"/logistica/tickets/{ticket_id}/responder", {"respuesta": response_text}).status_code, 302)
        self.assertEqual(tecman._load_tickets_raw()[0], after_response)

        resolution = "Compra entregada a la sucursal."
        self.assertEqual(self.post(f"/logistica/tickets/{ticket_id}/resolver", {"respuesta": resolution}).status_code, 302)
        resolved = copy.deepcopy(tecman._load_tickets_raw()[0])
        self.assertEqual((resolved["estado"], resolved["compra_np_estado"]), ("Resuelto", "Resuelto"))
        self.assertEqual(resolved["logistica_resolucion_actor"], tecman.PREPARADOR_DABRA_NAME)
        self.assertEqual(self.post(f"/logistica/tickets/{ticket_id}/resolver", {"respuesta": resolution}).status_code, 302)
        self.assertEqual(tecman._load_tickets_raw()[0], resolved)

        self.branch_session()
        tracking = self.client.get(f"/estado/{ticket_id}")
        self.assertEqual(tracking.status_code, 200)
        self.assertIn(b"Resuelto", tracking.data)
        self.assertIn(b"Respuesta de Log", tracking.data)
        self.assertIn(resolution.encode(), tracking.data)
        self.assertIn(b"Ticket resuelto por Log", tracking.data)

    def test_clasificacion_exacta_permisos_csrf_ids_y_rechazos_sin_mutacion(self):
        real = self.create_real_ticket()
        broad_text = {
            "id": 99,
            "sucursal": "Sucursal 011",
            "categoria": "Otro",
            "subcategoria": "Otro",
            "tipo": "incidente",
            "descripcion": "Comprar librería no productiva",
            "estado": "Nuevo",
            "creado": "2026-09-29T10:00:00",
            "actualizado": "2026-09-29T10:00:00",
        }
        wrong_type = dict(broad_text, id=100, categoria="Compras no productivas")
        tecman.save_tickets([real, broad_text, wrong_type])
        before = Path(tecman.TICKETS_FILE).read_bytes()

        self.logistics_session()
        inbox = self.client.get("/logistica/tickets")
        self.assertIn(f"#{real['id']}".encode(), inbox.data)
        self.assertNotIn(b"#99", inbox.data)
        self.assertNotIn(b"#100", inbox.data)
        self.assertEqual(Path(tecman.TICKETS_FILE).read_bytes(), before)
        self.assertEqual(self.client.get("/logistica/tickets/99").status_code, 404)
        self.assertEqual(self.post("/logistica/tickets/99/en-proceso").status_code, 404)
        self.assertEqual(Path(tecman.TICKETS_FILE).read_bytes(), before)

        no_csrf = self.client.post(f"/logistica/tickets/{real['id']}/en-proceso")
        self.assertEqual(no_csrf.status_code, 400)
        self.assertEqual(Path(tecman.TICKETS_FILE).read_bytes(), before)

        self.logistics_session(logistica_role="garin", logistica_user="garin@grupodexter.com.ar")
        self.assertEqual(self.client.get("/logistica/tickets").status_code, 403)
        self.assertEqual(Path(tecman.TICKETS_FILE).read_bytes(), before)

        self.logistics_session(auth_provider="local_logistica")
        self.assertEqual(self.client.get("/logistica/tickets").status_code, 403)
        self.assertEqual(Path(tecman.TICKETS_FILE).read_bytes(), before)

        original_users = copy.deepcopy(tecman._load_users_json())
        try:
            tecman._save_users_json({"users": [{
                "id": "logistica-revocada", "username": "hdiosque",
                "email": tecman.PREPARADOR_DABRA_EMAIL,
                "role": tecman.PREPARADOR_DABRA_ROLE, "status": "disabled",
                "session_version": 2,
            }]})
            self.logistics_session(auth_user_id="logistica-revocada", auth_session_version=1)
            self.assertEqual(self.client.get("/logistica/tickets").status_code, 403)
            self.assertEqual(Path(tecman.TICKETS_FILE).read_bytes(), before)
        finally:
            tecman._save_users_json(original_users)

        self.logistics_session()
        self.assertEqual(self.post(f"/logistica/tickets/{real['id']}/responder", {"respuesta": ""}).status_code, 409)
        self.assertEqual(Path(tecman.TICKETS_FILE).read_bytes(), before)

    def test_estado_final_bloquea_acciones_distintas_sin_mutar(self):
        ticket = self.create_real_ticket()
        ticket["estado"] = "Cerrado"
        tecman.save_tickets([ticket])
        before = Path(tecman.TICKETS_FILE).read_bytes()
        self.logistics_session()
        self.assertEqual(self.post(f"/logistica/tickets/{ticket['id']}/responder", {"respuesta": "No corresponde"}).status_code, 409)
        self.assertEqual(self.post(f"/logistica/tickets/{ticket['id']}/resolver", {"respuesta": "No corresponde"}).status_code, 409)
        self.assertEqual(Path(tecman.TICKETS_FILE).read_bytes(), before)


class SimulatedDbTicketWorkflowTests(unittest.TestCase):
    def test_mutacion_db_simulada_persiste_el_mismo_ticket_sin_duplicarlo(self):
        rows = [{
            "id": "db-7",
            "sucursal": "Sucursal 014",
            "categoria": "Compras no productivas",
            "subcategoria": "Librería",
            "tipo": "compra_no_productiva",
            "descripcion": "Etiquetas",
            "estado": "Nuevo",
            "creado": "2026-09-29T10:00:00",
            "actualizado": "2026-09-29T10:00:00",
        }]
        self.assertTrue(is_non_productive_purchase_ticket(rows[0]))
        start = mutate_purchase_ticket(rows, "db-7", "start", "Preparador Dabra Central")
        reply = mutate_purchase_ticket(rows, "db-7", "respond", "Preparador Dabra Central", "En compra")
        resolved = mutate_purchase_ticket(rows, "db-7", "resolve", "Preparador Dabra Central", "Entregado")
        duplicate = mutate_purchase_ticket(rows, "db-7", "resolve", "Preparador Dabra Central", "Entregado")
        self.assertTrue(start["changed"] and reply["changed"] and resolved["changed"])
        self.assertTrue(duplicate["idempotent"])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["estado"], "Resuelto")
        self.assertEqual([n["tipo"] for n in rows[0]["notas"]],
                         ["logistica_en_proceso", "logistica_respuesta", "logistica_resuelto"])

        snapshot = copy.deepcopy(rows)
        with self.assertRaises(LogisticsError):
            mutate_purchase_ticket(rows, "db-7", "respond", "Preparador Dabra Central", "otra")
        self.assertEqual(rows, snapshot)


if __name__ == "__main__":
    unittest.main()
