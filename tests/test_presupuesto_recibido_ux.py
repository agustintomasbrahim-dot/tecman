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


class PresupuestoRecibidoUXTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.original_paths = tecman.TICKETS_FILE, tecman.NOTIF_ADMIN_FILE, tecman.TICKET_DOCUMENTOS_DIR
        tecman.TICKETS_FILE = root / "tickets.json"
        tecman.NOTIF_ADMIN_FILE = root / "notif_admin.json"
        tecman.TICKET_DOCUMENTOS_DIR = root / "uploads" / "ticket_documentos"
        tecman.TICKET_DOCUMENTOS_DIR.mkdir(parents=True)
        tecman.USE_DB = False
        tecman.app.config.update(TESTING=True, SECRET_KEY="presupuesto-recibido-test")
        self.client = tecman.app.test_client()
        self.received = {
            "id": 88001,
            "sucursal": "Sucursal 076",
            "categoria": "Presupuestos",
            "subcategoria": "Plomería",
            "descripcion": "Reparar pérdida en depósito",
            "prioridad": 2,
            "estado": "Nuevo",
            "estado_presupuesto": "Nuevo",
            "asignado": "Administración",
            "proveedor_presupuesto": "Proveedor Real",
            "observaciones": "",
            "creado": "2026-09-24T10:00:00",
            "actualizado": "2026-09-24T10:00:00",
            "notas": [{"autor": "Sucursal", "fecha": "2026-09-24T10:00:00", "texto": "Cotización adjuntada"}],
            "presupuestos": [{
                "autor": "Sucursal",
                "proveedor": "Proveedor Real",
                "fecha": "2026-09-24T10:00:00",
                "detalle": "Reparación completa",
                "monto": "150000",
                "moneda": "ARS",
                "archivo": "cotizacion.pdf",
                "archivo_nombre": "Cotización.pdf",
                "archivo_seguro": True,
            }],
        }
        self.ordinary = {
            "id": 88002,
            "sucursal": "Sucursal 078",
            "categoria": "Mantenimiento",
            "subcategoria": "Electricidad",
            "descripcion": "Revisar tablero",
            "prioridad": 3,
            "estado": "Nuevo",
            "asignado": "Administración",
            "observaciones": "",
            "creado": "2026-09-24T11:00:00",
            "actualizado": "2026-09-24T11:00:00",
            "notas": [],
        }
        self.awaiting = dict(
            self.ordinary,
            id=88003,
            categoria="Presupuestos",
            estado_presupuesto="Nuevo",
            proveedor_presupuesto="Proveedor Real",
        )
        tecman.save_tickets([self.received, self.ordinary, self.awaiting])
        tecman.save_notif_admin({"notificaciones": []})
        self._admin()

    def tearDown(self):
        tecman.TICKETS_FILE, tecman.NOTIF_ADMIN_FILE, tecman.TICKET_DOCUMENTOS_DIR = self.original_paths
        tecman.USE_DB = False
        self.temp.cleanup()

    def _admin(self):
        with self.client.session_transaction() as session:
            session.clear()
            session.update(user="admin-test", rol="admin", nombre="Admin Test", _csrf_token="csrf-test")

    def _saved(self, ticket_id=88001):
        return next(item for item in tecman.load_tickets() if item["id"] == ticket_id)

    def _post(self, decision, detail=""):
        return self.client.post(
            "/admin/ticket/88001",
            data={
                "_csrf_token": "csrf-test",
                "accion": "presupuesto_recibido_accion",
                "decision": decision,
                "detalle_decision": detail,
            },
        )

    def test_detector_es_conservador_y_documenta_los_dos_componentes(self):
        self.assertTrue(tecman._es_ticket_con_presupuesto_recibido(self.received))
        self.assertFalse(tecman._es_ticket_con_presupuesto_recibido(self.ordinary))
        self.assertFalse(tecman._es_ticket_con_presupuesto_recibido(self.awaiting))
        self.assertFalse(tecman._es_ticket_con_presupuesto_recibido({"presupuestos": [{"detalle": "Sin trazabilidad"}]}))
        self.assertFalse(tecman._es_ticket_con_presupuesto_recibido({"presupuestos": [{"fecha": "2026-09-24"}]}))

    def test_render_real_prioriza_decision_archivo_seguro_historial_y_avanzados(self):
        response = self.client.get("/admin/ticket/88001")
        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        for text in (
            "Presupuesto recibido", "Decisión del ticket #88001", "Sucursal 076",
            "Reparar pérdida en depósito", "Proveedor Real", "ARS 150000",
            "Cotización.pdf", "/tickets/88001/documentos/presupuestos/cotizacion.pdf",
            "Pendiente de decisión", "Próxima acción:", "Revisar el presupuesto y decidir",
            "Aprobar", "Rechazar / devolver", "Pedir aclaración", "Comunicar respuesta",
            "Historial", "Cotización adjuntada", "Detalles avanzados",
        ):
            self.assertIn(text, page)
        self.assertEqual(page.count("Próxima acción:"), 1)
        self.assertLess(page.index("Presupuesto recibido"), page.index("Detalles avanzados"))

    def test_datos_incompletos_se_omiten_sin_inventar(self):
        ticket = copy.deepcopy(self.received)
        ticket.pop("proveedor_presupuesto")
        ticket["presupuestos"] = [{"autor": "Sucursal", "fecha": "", "detalle": "Sólo detalle"}]
        tecman.save_tickets([ticket, self.ordinary, self.awaiting])
        page = self.client.get("/admin/ticket/88001").get_data(as_text=True)
        summary = page.split('<section class="quote-decision"', 1)[1].split('<section class="card"', 1)[0]
        self.assertIn("Solicitud", summary)
        self.assertNotIn("Proveedor</span>", summary)
        self.assertNotIn("Monto", summary)
        self.assertNotIn("Fecha recibida", summary)
        self.assertNotIn("Archivo</span>", summary)

    def test_tickets_sin_presupuesto_conservan_vista_y_rutas_sin_mutacion(self):
        ordinary_page = self.client.get("/admin/ticket/88002").get_data(as_text=True)
        awaiting_page = self.client.get("/admin/ticket/88003").get_data(as_text=True)
        self.assertNotIn("Decisión del ticket", ordinary_page)
        self.assertNotIn("Detalles avanzados", ordinary_page)
        self.assertIn("Proveedor / presupuesto", ordinary_page)
        self.assertNotIn("Decisión del ticket", awaiting_page)
        before = copy.deepcopy(tecman.load_tickets())
        response = self.client.post(
            "/admin/ticket/88002",
            data={
                "_csrf_token": "csrf-test",
                "accion": "presupuesto_recibido_accion",
                "decision": "aprobar",
            },
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(tecman.load_tickets(), before)

    def test_permisos_y_csrf_rechazan_sin_mutar(self):
        before = copy.deepcopy(tecman.load_tickets())
        response = self.client.post(
            "/admin/ticket/88001",
            data={"accion": "presupuesto_recibido_accion", "decision": "aprobar"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(tecman.load_tickets(), before)
        with self.client.session_transaction() as session:
            session.clear()
            session.update(user="tecnico-test", rol="tecnico", nombre="Técnico", _csrf_token="csrf-test")
        denied = self.client.get("/admin/ticket/88001")
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(tecman.load_tickets(), before)

    def test_aprobar_reutiliza_aviso_a_rita_y_deja_historial(self):
        with patch.object(tecman, "_notificar_requisicion_rita", return_value="sent") as notify:
            response = self._post("aprobar")
        self.assertEqual(response.status_code, 302)
        ticket = self._saved()
        self.assertEqual(ticket["estado_presupuesto"], "Aprobado")
        self.assertTrue(ticket["requiere_requisicion"])
        self.assertEqual(ticket["presupuesto_etapa"], "aprobado")
        self.assertIn("Decisión de presupuesto: aprobado", ticket["notas"][-1]["texto"])
        self.assertEqual(ticket["notificaciones"][-1]["visibilidad"], "sucursal")
        notify.assert_called_once()
        page = self.client.get("/admin/ticket/88001").get_data(as_text=True)
        self.assertIn("Preparar la requisición", page)
        self.assertIn("Decisión de presupuesto: aprobado", page)

    def test_devolver_aclarar_y_comunicar_validan_y_avisan_al_destinatario(self):
        before = copy.deepcopy(self._saved())
        invalid = self._post("rechazar", "")
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(self._saved(), before)

        clarified = self._post("aclarar", "Confirmar alcance y plazo")
        self.assertEqual(clarified.status_code, 302)
        ticket = self._saved()
        self.assertEqual(ticket["estado_respuesta"], "Aclaración solicitada")
        self.assertIn("Confirmar alcance y plazo", ticket["notificaciones_prov"][-1]["texto"])
        self.assertIn("Aclaración solicitada al proveedor", ticket["notas"][-1]["texto"])

        communicated = self._post("comunicar", "Estamos revisando la propuesta")
        self.assertEqual(communicated.status_code, 302)
        ticket = self._saved()
        self.assertEqual(ticket["estado_respuesta"], "Respuesta comunicada")
        self.assertEqual(ticket["notificaciones"][-1]["texto"], "Estamos revisando la propuesta")
        self.assertEqual(ticket["notificaciones"][-1]["visibilidad"], "sucursal")

        rejected = self._post("rechazar", "Solicitar una alternativa")
        self.assertEqual(rejected.status_code, 302)
        ticket = self._saved()
        self.assertEqual(ticket["estado_presupuesto"], "Rechazado")
        self.assertEqual(ticket["presupuesto_etapa"], "rechazado")
        self.assertIn("Presupuesto devuelto / rechazado", ticket["notas"][-1]["texto"])
        self.assertEqual(ticket["notificaciones"][-1]["texto"], "Solicitar una alternativa")


if __name__ == "__main__":
    unittest.main()
