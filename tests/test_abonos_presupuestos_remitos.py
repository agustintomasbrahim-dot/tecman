import copy
import io
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


PDF = b"%PDF-1.4\n% test\n1 0 obj<<>>endobj\n%%EOF\n"


class AbonosPresupuestosRemitosTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.original_paths = (
            tecman.TICKETS_FILE,
            tecman.NOTIF_ADMIN_FILE,
            tecman.TICKET_DOCUMENTOS_DIR,
        )
        tecman.TICKETS_FILE = root / "tickets.json"
        tecman.NOTIF_ADMIN_FILE = root / "notif_admin.json"
        tecman.TICKET_DOCUMENTOS_DIR = root / "uploads" / "ticket_documentos"
        tecman.TICKET_DOCUMENTOS_DIR.mkdir(parents=True)
        tecman.USE_DB = False
        tecman.app.config.update(TESTING=True, SECRET_KEY="abonos-test")
        self.client = tecman.app.test_client()
        self.ticket = {
            "id": 77001,
            "sucursal": "Sucursal 076",
            "sucursal_num": "076",
            "categoria": "Mantenimiento",
            "subcategoria": "Plomería",
            "descripcion": "Pérdida de agua en depósito",
            "prioridad": 2,
            "estado": "Nuevo",
            "asignado": "Gustavo Avellaneda",
            "observaciones": "",
            "creado": "2026-09-22T10:00:00",
            "actualizado": "2026-09-22T10:00:00",
            "notas": [],
        }
        self.other = dict(self.ticket, id=77002, sucursal="Sucursal 078", sucursal_num="078")
        tecman.save_tickets([self.ticket, self.other])
        tecman.save_notif_admin({"notificaciones": []})

    def tearDown(self):
        tecman.TICKETS_FILE, tecman.NOTIF_ADMIN_FILE, tecman.TICKET_DOCUMENTOS_DIR = self.original_paths
        tecman.USE_DB = False
        self.temp.cleanup()

    def _admin(self):
        with self.client.session_transaction() as sess:
            sess.clear()
            sess.update(user="admin-test", rol="admin", nombre="Admin Test", _csrf_token="csrf-test")

    def _branch(self, sucursal="Sucursal 076"):
        with self.client.session_transaction() as sess:
            sess.clear()
            sess.update(suc_user="sucursal-test", suc_nombre=sucursal, _csrf_token="csrf-test")

    def _provider(self):
        with self.client.session_transaction() as sess:
            sess.clear()
            sess.update(
                prov_user="preview.admin",
                prov_nombre="Gustavo Avellaneda",
                prov_tipo_cuenta="abono_fijo",
                prov_full_access=True,
                auth_provider="entra",
                entra_role="proveedor",
                _csrf_token="csrf-test",
            )

    def _saved(self, ticket_id=77001):
        return next(t for t in tecman.load_tickets() if t["id"] == ticket_id)

    def _define_uncovered(self):
        self._admin()
        response = self.client.post(
            "/admin/ticket/77001",
            data={
                "_csrf_token": "csrf-test",
                "accion": "definir_cobertura_abono",
                "cobertura_abono": "no_cubierto",
                "proveedor_presupuesto": "Gustavo Avellaneda",
                "detalle_cobertura_abono": "Trabajo fuera del alcance contractual",
            },
        )
        self.assertEqual(response.status_code, 302)

    def _upload_budget(self, amount="987654"):
        self._provider()
        return self.client.post(
            "/proveedor/ticket/77001",
            data={
                "_csrf_token": "csrf-test",
                "accion": "presupuesto",
                "detalle_presupuesto": "Reparación completa con materiales especiales",
                "monto_presupuesto": amount,
                "archivo_presupuesto": (io.BytesIO(PDF), "cotizacion-privada.pdf"),
            },
            content_type="multipart/form-data",
        )

    def test_cobertura_no_cubierta_reutiliza_portal_y_presupuesto_seguro(self):
        self._define_uncovered()
        ticket = self._saved()
        self.assertEqual(ticket["abono_cobertura"], "no_cubierto")
        self.assertEqual(ticket["estado_presupuesto"], "Pendiente")
        self.assertEqual(ticket["presupuesto_etapa"], "solicitado")
        self.assertTrue(ticket["requiere_presupuesto_proveedor"])

        response = self._upload_budget()
        self.assertEqual(response.status_code, 302)
        ticket = self._saved()
        budget = ticket["presupuestos"][-1]
        self.assertEqual(budget["monto"], "987654")
        self.assertTrue(budget["archivo_seguro"])
        stored = tecman.TICKET_DOCUMENTOS_DIR / "77001" / "presupuestos" / budget["archivo"]
        self.assertEqual(stored.read_bytes(), PDF)

        self._admin()
        admin_page = self.client.get("/admin/ticket/77001").get_data(as_text=True)
        self.assertIn("987654", admin_page)
        self.assertIn("cotizacion-privada.pdf", admin_page)
        download = self.client.get(f"/tickets/77001/documentos/presupuestos/{budget['archivo']}")
        self.assertEqual(download.status_code, 200)
        self.assertEqual(download.data, PDF)
        download.close()

    def test_sucursal_solo_ve_estado_y_comentario_publico_sin_economia(self):
        self._define_uncovered()
        self.assertEqual(self._upload_budget().status_code, 302)
        ticket = self._saved()
        budget = ticket["presupuestos"][-1]
        ticket.setdefault("notas", []).append({
            "autor": "Interno",
            "fecha": "2026-09-22T11:00:00",
            "texto": "Importe confidencial USD 999999 y archivo cotizacion-privada.pdf",
            "visibilidad": "interna",
        })
        legacy_name = "legacy-secret-budget.pdf"
        (tecman.UPLOADS_DIR / legacy_name).write_bytes(PDF)
        ticket["presupuestos"].append({
            "autor": "Interno", "fecha": "2026-09-22T11:00:00",
            "detalle": "Cotización histórica", "monto": "888888",
            "archivo": legacy_name, "archivo_nombre": legacy_name,
        })
        tecman.save_tickets([ticket, self.other])

        self._branch()
        page = self.client.get("/estado/77001").get_data(as_text=True)
        panel = self.client.get("/mi-panel").get_data(as_text=True)
        combined = page + panel
        self.assertIn("Estado del presupuesto", page)
        self.assertNotIn("987654", combined)
        self.assertNotIn("999999", combined)
        self.assertNotIn("888888", combined)
        self.assertNotIn("USD", combined)
        self.assertNotIn("cotizacion-privada.pdf", combined)
        self.assertNotIn("Reparación completa con materiales especiales", combined)
        self.assertNotIn("/documentos/presupuestos/", combined)

        denied = self.client.get(f"/tickets/77001/documentos/presupuestos/{budget['archivo']}")
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(self.client.get(f"/static/uploads/{legacy_name}").status_code, 403)

        self._admin()
        rejected = self.client.post(
            "/admin/ticket/77001",
            data={
                "_csrf_token": "csrf-test",
                "accion": "estado_presupuesto",
                "nuevo_estado_presupuesto": "Aprobado",
                "comentario_presupuesto": "Aprobado por $ 999999",
            },
        )
        self.assertEqual(rejected.status_code, 400)
        self.assertEqual(self._saved()["estado_presupuesto"], "Pendiente")

        with patch.object(tecman, "_notificar_requisicion_rita", return_value="sent"):
            accepted = self.client.post(
                "/admin/ticket/77001",
                data={
                    "_csrf_token": "csrf-test",
                    "accion": "estado_presupuesto",
                    "nuevo_estado_presupuesto": "Aprobado",
                    "comentario_presupuesto": "Aprobado para coordinar la ejecución",
                },
            )
        self.assertEqual(accepted.status_code, 302)
        self._branch()
        page = self.client.get("/estado/77001").get_data(as_text=True)
        self.assertIn("Estado del presupuesto: Aprobado", page)
        self.assertIn("Aprobado para coordinar la ejecución", page)
        self.assertNotIn("987654", page)

    def test_remito_requiere_scope_csrf_archivo_valido_y_bloquea_cierre(self):
        self._define_uncovered()
        self.assertEqual(self._upload_budget().status_code, 302)

        self._admin()
        with patch.object(tecman, "_notificar_requisicion_rita", return_value="sent"):
            approved = self.client.post(
                "/admin/ticket/77001",
                data={
                    "_csrf_token": "csrf-test",
                    "accion": "estado_presupuesto",
                    "nuevo_estado_presupuesto": "Aprobado",
                    "comentario_presupuesto": "Aprobado para ejecutar",
                },
            )
        self.assertEqual(approved.status_code, 302)

        self._provider()
        finished = self.client.post(
            "/proveedor/ticket/77001",
            data={"_csrf_token": "csrf-test", "accion": "hecho"},
        )
        self.assertEqual(finished.status_code, 302)
        self.assertEqual(self._saved()["abono_remito_estado"], "pendiente_carga")
        self.assertEqual(self._saved()["estado"], "Pendiente")

        self._admin()
        close_before = self.client.post(
            "/admin/ticket/77001",
            data={
                "_csrf_token": "csrf-test", "estado": "Cerrado",
                "asignado": "Gustavo Avellaneda", "prioridad": "2", "observaciones": "",
            },
        )
        self.assertEqual(close_before.status_code, 409)

        self._branch("Sucursal 078")
        before = copy.deepcopy(self._saved())
        wrong_scope = self.client.post(
            "/estado/77001/remito-trabajo",
            data={"_csrf_token": "csrf-test", "remito": (io.BytesIO(PDF), "remito.pdf")},
            content_type="multipart/form-data",
        )
        self.assertEqual(wrong_scope.status_code, 403)
        self.assertEqual(self._saved(), before)

        self._branch()
        missing_csrf = self.client.post(
            "/estado/77001/remito-trabajo",
            data={"remito": (io.BytesIO(PDF), "remito.pdf")},
            content_type="multipart/form-data",
        )
        self.assertEqual(missing_csrf.status_code, 400)
        invalid = self.client.post(
            "/estado/77001/remito-trabajo",
            data={"_csrf_token": "csrf-test", "remito": (io.BytesIO(b"not a pdf"), "remito.pdf")},
            content_type="multipart/form-data",
        )
        self.assertEqual(invalid.status_code, 400)
        self.assertFalse(list(tecman.TICKET_DOCUMENTOS_DIR.rglob("*.pdf"))[-1:] and any(
            p.parent.name == "remitos" for p in tecman.TICKET_DOCUMENTOS_DIR.rglob("*.pdf")
        ))

        uploaded = self.client.post(
            "/estado/77001/remito-trabajo",
            data={
                "_csrf_token": "csrf-test",
                "comentario": "Trabajo recibido conforme",
                "remito": (io.BytesIO(PDF), "remito-final.pdf"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(uploaded.status_code, 302)
        ticket = self._saved()
        remito = ticket["abono_remitos"][-1]
        self.assertEqual(ticket["abono_remito_estado"], "pendiente_validacion")
        self.assertNotEqual(remito["archivo"], remito["nombre_original"])

        own_file = self.client.get(f"/tickets/77001/documentos/remitos/{remito['archivo']}")
        self.assertEqual(own_file.status_code, 200)
        own_file.close()
        self.assertEqual(
            self.client.get(f"/static/uploads/ticket_documentos/77001/remitos/{remito['archivo']}").status_code,
            404,
        )
        self._branch("Sucursal 078")
        self.assertEqual(
            self.client.get(f"/tickets/77001/documentos/remitos/{remito['archivo']}").status_code,
            403,
        )

        self._admin()
        validation = self.client.post(
            "/admin/ticket/77001",
            data={
                "_csrf_token": "csrf-test",
                "accion": "validar_remito_abono",
                "documento_id": remito["id"],
                "observacion": "Conforme",
            },
        )
        self.assertEqual(validation.status_code, 302)
        self.assertEqual(self._saved()["abono_remito_estado"], "validado")
        closed = self.client.post(
            "/admin/ticket/77001",
            data={
                "_csrf_token": "csrf-test", "estado": "Cerrado",
                "asignado": "Gustavo Avellaneda", "prioridad": "2", "observaciones": "",
            },
        )
        self.assertEqual(closed.status_code, 302)
        self.assertEqual(self._saved()["estado"], "Cerrado")

    def test_operaciones_nuevas_rechazan_csrf_sin_mutar(self):
        self._admin()
        before = copy.deepcopy(tecman.load_tickets())
        response = self.client.post(
            "/admin/ticket/77001",
            data={
                "accion": "definir_cobertura_abono",
                "cobertura_abono": "cubierto",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(tecman.load_tickets(), before)

        self._define_uncovered()
        self._provider()
        before = copy.deepcopy(tecman.load_tickets())
        response = self.client.post(
            "/proveedor/ticket/77001",
            data={
                "accion": "presupuesto",
                "detalle_presupuesto": "Detalle",
                "monto_presupuesto": "123",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(tecman.load_tickets(), before)


    def test_fallo_de_persistencia_no_deja_presupuesto_huerfano(self):
        self._define_uncovered()
        self._provider()
        with patch.object(tecman, "save_tickets", side_effect=RuntimeError("fallo simulado")):
            with self.assertRaises(RuntimeError):
                self.client.post(
                    "/proveedor/ticket/77001",
                    data={
                        "_csrf_token": "csrf-test",
                        "accion": "presupuesto",
                        "detalle_presupuesto": "Reparación fuera de abono",
                        "monto_presupuesto": "1000",
                        "archivo_presupuesto": (io.BytesIO(PDF), "fallo.pdf"),
                    },
                    content_type="multipart/form-data",
                )
        self.assertEqual(list(tecman.TICKET_DOCUMENTOS_DIR.rglob("*.pdf")), [])
        self.assertEqual(tecman.load_notif_admin().get("notificaciones", []), [])


    def test_cubierto_y_persistencia_db_conservan_decision_e_historial(self):
        rows = [copy.deepcopy(self.ticket)]
        replaced = {}
        ticket_model = object()

        def db_list(model):
            self.assertIs(model, ticket_model)
            return copy.deepcopy(rows)

        def db_replace(model, values):
            replaced[model] = copy.deepcopy(values)

        self._admin()
        with patch.object(tecman, "TicketDB", ticket_model, create=True), \
             patch.object(tecman, "_db_list", side_effect=db_list), \
             patch.object(tecman, "_db_replace", side_effect=db_replace), \
             patch.object(tecman, "_atomic_write") as atomic_write:
            tecman.USE_DB = True
            try:
                response = self.client.post(
                    "/admin/ticket/77001",
                    data={
                        "_csrf_token": "csrf-test",
                        "accion": "definir_cobertura_abono",
                        "cobertura_abono": "cubierto",
                        "detalle_cobertura_abono": "Incluido en el alcance mensual",
                    },
                )
            finally:
                tecman.USE_DB = False

        self.assertEqual(response.status_code, 302)
        stored = replaced[ticket_model][0]
        self.assertEqual(stored["abono_cobertura"], "cubierto")
        expected_provider = tecman.get_proveedor_abono_sucursal("076")
        self.assertEqual(stored["abono_proveedor"], expected_provider)
        self.assertEqual(stored["asignado_proveedor"], expected_provider)
        self.assertEqual(stored["abono_historial"][-1]["accion"], "cobertura_cubierto")
        atomic_write.assert_called_once()


if __name__ == "__main__":
    unittest.main()
