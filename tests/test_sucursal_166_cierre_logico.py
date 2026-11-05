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
from sucursales_data import SUCURSALES_INFO  # noqa: E402


class Sucursal166CierreLogicoTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.docs = self.root / "ticket_documentos"
        self.docs.mkdir(parents=True)
        self.original_docs = tecman.TICKET_DOCUMENTOS_DIR
        tecman.TICKET_DOCUMENTOS_DIR = self.docs
        tecman.app.config.update(TESTING=True, SECRET_KEY="sucursal-166-cierre-test")
        self.client = tecman.app.test_client()
        self.ticket = {
            "id": 16601,
            "sucursal": "Sucursal 166",
            "sucursal_num": "166",
            "categoria": "Reparaciones",
            "subcategoria": "General",
            "descripcion": "Histórico Rosario Peatonal",
            "prioridad": 2,
            "estado": "Nuevo",
            "asignado": "Responsable histórico",
            "observaciones": "Dato conservado",
            "creado": "2026-10-01T10:00:00",
            "actualizado": "2026-10-01T10:00:00",
            "fotos": [],
            "notas": [],
            "abono_remitos": [{"id": "remito-166", "archivo": "remito-166.pdf", "nombre_original": "remito.pdf"}],
        }
        remitos = self.docs / str(self.ticket["id"]) / "remitos"
        remitos.mkdir(parents=True)
        (remitos / "remito-166.pdf").write_bytes(b"%PDF-1.4\nhistorico-166\n%%EOF\n")
        self._admin_session()

    def tearDown(self):
        tecman.TICKET_DOCUMENTOS_DIR = self.original_docs
        self.temp.cleanup()

    def _admin_session(self):
        with self.client.session_transaction() as session:
            session.clear()
            session["user"] = "admin-test"
            session["nombre"] = "Administración"
            session["rol"] = "admin"

    def test_catalogo_activo_usuario_y_correo_quedan_revocados_sin_borrar_metadata(self):
        self.assertIn("166", tecman.SUCURSALES_CERRADAS)
        self.assertNotIn("Sucursal 166", tecman.SUCURSALES)
        self.assertNotIn("166", tecman.SUCURSAL_EMAILS)
        self.assertNotIn("suc166", tecman.SUCURSAL_USERS)
        self.assertIsNone(tecman._sucursal_user_from_entra_email("suc166@grupodabra.com.ar"))
        self.assertNotIn("166", tecman._SUCURSALES_INFRA)
        self.assertEqual(SUCURSALES_INFO["166"]["tienda"], "Moov Rosario Peatonal")
        self.assertEqual(SUCURSALES_INFO["166"]["direccion"], "Cordoba 1240")

        proveedores_crudos = [p for p in tecman.PROVEEDORES if "166" in p.get("sucursales", [])]
        self.assertTrue(proveedores_crudos)
        self.assertTrue(all("166" not in p.get("sucursales", []) for p in tecman._proveedores_enriquecidos()))

    def test_supervisor_y_portal_no_recuperan_acceso_a_la_sucursal_cerrada(self):
        with tecman.app.test_request_context("/"):
            tecman.session["suc_general"] = True
            tecman.session["suc_scope_nums"] = ["166", "167"]
            self.assertEqual(tecman._sucursal_session_scope_nums(), {"167"})
            self.assertFalse(tecman._sucursal_session_can_access_value("Sucursal 166"))

        with self.client.session_transaction() as session:
            session.clear()
            session["suc_user"] = "suc166"
            session["suc_nombre"] = "Sucursal 166"
            session["suc_general"] = False
        blocked = self.client.get("/mi-panel")
        self.assertEqual(blocked.status_code, 403)
        with self.client.session_transaction() as session:
            self.assertNotIn("suc_user", session)

    def test_vistas_activas_excluyen_ticket_y_mapa_de_166(self):
        active = dict(self.ticket, id=16701, sucursal="Sucursal 167", sucursal_num="167", descripcion="Activo 167")
        with patch.object(tecman, "load_tickets", return_value=[copy.deepcopy(self.ticket), active]), \
             patch.object(tecman, "sync_alertas_syh"), \
             patch.object(tecman, "load_notif_admin", return_value={"notificaciones": []}):
            panel = self.client.get("/admin?vista=tabla")
            mapa = self.client.get("/admin/mapa")
        self.assertEqual(panel.status_code, 200)
        self.assertNotIn("#16601", panel.get_data(as_text=True))
        self.assertIn("#16701", panel.get_data(as_text=True))
        self.assertEqual(mapa.status_code, 200)
        self.assertNotIn("Moov Rosario Peatonal", mapa.get_data(as_text=True))

    def test_administracion_consulta_ficha_ticket_y_adjunto_historicos_sin_mutar(self):
        with patch.object(tecman, "load_tickets", return_value=[copy.deepcopy(self.ticket)]), \
             patch.object(tecman, "load_presupuestos", return_value={"presupuestos": []}), \
             patch.object(tecman, "save_tickets") as save_tickets:
            ficha = self.client.get("/admin/sucursal/166")
            detalle = self.client.get("/admin/ticket/16601")
            blocked = self.client.post("/admin/ticket/16601", data={"accion": "responder_suc"})
            adjunto = self.client.get("/tickets/16601/documentos/remitos/remito-166.pdf")

        self.assertEqual(ficha.status_code, 200)
        ficha_html = ficha.get_data(as_text=True)
        self.assertIn("Sucursal cerrada · consulta histórica", ficha_html)
        self.assertIn("Moov Rosario Peatonal", ficha_html)
        self.assertIn("16601", ficha_html)
        self.assertEqual(detalle.status_code, 200)
        detalle_html = detalle.get_data(as_text=True)
        self.assertIn("Sucursal cerrada · consulta histórica", detalle_html)
        self.assertIn("Histórico Rosario Peatonal", detalle_html)
        self.assertEqual(blocked.status_code, 409)
        self.assertIn("sólo para consulta", blocked.get_data(as_text=True))
        self.assertEqual(adjunto.status_code, 200)
        self.assertEqual(adjunto.data, b"%PDF-1.4\nhistorico-166\n%%EOF\n")
        adjunto.close()
        save_tickets.assert_not_called()

    def test_pedido_e_inventario_historicos_no_se_mueven_ni_generan_operaciones(self):
        material = {
            **copy.deepcopy(self.ticket),
            "id": 16602,
            "categoria": "Materiales",
            "subcategoria": "Solicitud de materiales",
            "tipo": "materiales",
            "categoria_mat": "Electricidad",
            "subitem_mat": "Reflector",
            "cantidad_mat": "2",
            "zona_afectada": "Salón",
        }
        stock = {
            "central": {"Electricidad > Reflector": {"cantidad": 10, "precio_unitario": 1}},
            "sucursales": {
                "Sucursal 166": {"Electricidad > Reflector": 7},
                "Sucursal 167": {"Electricidad > Reflector": 3},
            },
        }
        before = copy.deepcopy(stock)
        with patch.object(tecman, "load_tickets", return_value=[material]), \
             patch.object(tecman, "load_stock", return_value=stock), \
             patch.object(tecman, "load_transfers", return_value=[]), \
             patch.object(tecman, "save_tickets") as save_tickets, \
             patch.object(tecman, "save_stock") as save_stock:
            detalle = self.client.get("/admin/pedido/16602")
            blocked = self.client.post("/admin/pedido/16602", data={"accion": "enviado"})
            guia = self.client.get("/admin/pedido/16602/guia")
            stock_page = self.client.get("/admin/stock")

        self.assertEqual(detalle.status_code, 200)
        self.assertIn("Sucursal cerrada · consulta histórica", detalle.get_data(as_text=True))
        self.assertEqual(blocked.status_code, 409)
        self.assertEqual(guia.status_code, 409)
        self.assertNotIn("Sucursal 166", stock_page.get_data(as_text=True))
        self.assertIn("Sucursal 167", stock_page.get_data(as_text=True))
        self.assertEqual(stock, before)
        save_tickets.assert_not_called()
        save_stock.assert_not_called()

    def test_posts_manipulados_no_cargan_ni_transfieren_stock_a_166(self):
        stock = {
            "central": {"Electricidad > Reflector": {"cantidad": 10, "precio_unitario": 1}},
            "sucursales": {"Sucursal 166": {"Electricidad > Reflector": 7}},
        }
        before = copy.deepcopy(stock)
        with patch.object(tecman, "_validate_csrf", return_value=True), \
             patch.object(tecman, "load_stock", return_value=stock), \
             patch.object(tecman, "load_transfers", return_value=[]), \
             patch.object(tecman, "save_stock") as save_stock, \
             patch.object(tecman, "save_transfers") as save_transfers, \
             patch.object(tecman, "registrar_movimiento") as registrar_movimiento:
            alta = self.client.post("/admin/stock/add", data={
                "categoria_mat": "Electricidad",
                "subitem": "Reflector",
                "cantidad": "2",
                "ubicacion": "Sucursal 166",
            })
            transferencia = self.client.post("/admin/stock/transfer", data={
                "item": "Electricidad > Reflector",
                "cantidad": "2",
                "destino": "Sucursal 166",
            })

        self.assertEqual(alta.status_code, 409)
        self.assertEqual(transferencia.status_code, 409)
        self.assertEqual(stock, before)
        save_stock.assert_not_called()
        save_transfers.assert_not_called()
        registrar_movimiento.assert_not_called()


if __name__ == "__main__":
    unittest.main()
