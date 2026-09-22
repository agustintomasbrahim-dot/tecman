import copy
import io
import os
import tempfile
import unittest
from pathlib import Path

_TEST_ROOT = tempfile.TemporaryDirectory()
os.environ["TECMAN_DATA_DIR"] = str(Path(_TEST_ROOT.name) / "data")
os.environ["TECMAN_UPLOADS_DIR"] = str(Path(_TEST_ROOT.name) / "uploads")
os.environ.pop("DATABASE_URL", None)

import app as tecman  # noqa: E402


class FumigacionesWorkflowTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.original = (tecman.TICKETS_FILE, tecman.NOTIF_ADMIN_FILE, tecman.FUMIGACION_REMITOS_DIR)
        tecman.TICKETS_FILE = root / "tickets.json"
        tecman.NOTIF_ADMIN_FILE = root / "notif_admin.json"
        tecman.FUMIGACION_REMITOS_DIR = root / "uploads" / "fumigacion_remitos"
        tecman.FUMIGACION_REMITOS_DIR.mkdir(parents=True)
        tecman.USE_DB = False
        tecman.app.config.update(TESTING=True, SECRET_KEY="fumigacion-test")
        self.ticket = {
            "id": 920001,
            "sucursal": "Sucursal 014",
            "sucursal_num": "014",
            "categoria": "Mantenimiento",
            "subcategoria": "Servicio preventivo",
            "descripcion": "Control mensual",
            "prioridad": 3,
            "estado": "Abierto",
            "asignado": "Cesar Ricardo Fratini",
            "asignado_proveedor": "Cesar Ricardo Fratini",
            "etapa_prov": "recibido",
            "creado": "2026-09-20T10:00:00",
            "actualizado": "2026-09-20T10:00:00",
            "notas": [],
        }
        self.other = dict(self.ticket, id=920002, sucursal="Sucursal 020", sucursal_num="020", notas=[])
        self.not_fumigation = dict(
            self.ticket,
            id=920003,
            asignado="Martin Microglobal",
            asignado_proveedor="Martin Microglobal",
            subcategoria="Vidrios",
            notas=[],
        )
        tecman.save_tickets([self.ticket, self.other, self.not_fumigation])
        tecman.save_notif_admin({"notificaciones": []})
        self.client = tecman.app.test_client()

    def tearDown(self):
        tecman.TICKETS_FILE, tecman.NOTIF_ADMIN_FILE, tecman.FUMIGACION_REMITOS_DIR = self.original
        tecman.USE_DB = False
        self.temp.cleanup()

    def _branch(self, label="Sucursal 014"):
        with self.client.session_transaction() as sess:
            sess.clear()
            sess.update(suc_user="test", suc_nombre=label, _csrf_token="csrf-test")

    def _provider(self):
        with self.client.session_transaction() as sess:
            sess.clear()
            sess.update(
                prov_user="frattini",
                prov_nombre="Cesar Ricardo Fratini",
                prov_tipo_cuenta="fumigacion",
                prov_session_version=1,
                _csrf_token="csrf-test",
            )

    def _admin(self):
        with self.client.session_transaction() as sess:
            sess.clear()
            sess.update(user="admin-test", nombre="Agustín", rol="admin", _csrf_token="csrf-test")

    def _saved(self, ticket_id=920001):
        return next(t for t in tecman.load_tickets() if t["id"] == ticket_id)

    def _mark_realized(self, ticket_id=920001):
        self._provider()
        response = self.client.post(
            f"/proveedor/ticket/{ticket_id}",
            data={"_csrf_token": "csrf-test", "accion": "relevado"},
        )
        self.assertEqual(response.status_code, 302)

    def _upload(self, ticket_id=920001, name="remito.pdf", body=b"%PDF-1.4\nfixture", csrf="csrf-test"):
        return self.client.post(
            f"/suc/fumigaciones/{ticket_id}/remito",
            data={"_csrf_token": csrf, "comentario": "Trabajo conforme", "remito": (io.BytesIO(body), name)},
            content_type="multipart/form-data",
        )

    def test_panel_y_seccion_solo_exponen_scope_y_empty_state_por_proveedor(self):
        self._branch()
        panel = self.client.get("/mi-panel")
        self.assertEqual(panel.status_code, 200)
        self.assertIn("Fumigaciones", panel.get_data(as_text=True))
        page = self.client.get("/suc/fumigaciones")
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        self.assertIn("Todavía no hay visitas programadas", html)
        self.assertIn("Cesar Ricardo Fratini", html)
        self.assertNotIn("920002", html)

        self._branch("Sucursal 230")
        self.assertNotIn("Fumigaciones", self.client.get("/mi-panel").get_data(as_text=True))
        self.assertEqual(self.client.get("/suc/fumigaciones").status_code, 404)

    def test_programacion_clara_auditada_e_idempotente(self):
        self._provider()
        for _ in range(2):
            response = self.client.post(
                "/proveedor/ticket/920001",
                data={"_csrf_token": "csrf-test", "accion": "planificado", "fecha_visita": "2026-10-05"},
            )
            self.assertEqual(response.status_code, 302)
        ticket = self._saved()
        notices = [n for n in ticket["notificaciones"] if n.get("clave", "").startswith("fumigacion_programada:")]
        self.assertEqual(len(notices), 1)
        self.assertEqual(notices[0]["texto"], "Fumigación programada para 05/10/2026 · Proveedor: Cesar Ricardo Fratini · Ticket #920001")
        self.assertEqual(len([e for e in ticket["fumigacion_historial"] if e["accion"] == "visita_programada"]), 1)
        self.assertEqual(ticket["estado"], "En progreso")

    def test_relevado_deja_pendiente_carga_sin_cerrar_y_aviso_accionable(self):
        self._mark_realized()
        ticket = self._saved()
        self.assertEqual(ticket["fumigacion_estado"], "realizada")
        self.assertEqual(ticket["remito_estado"], "pendiente_carga")
        self.assertEqual(ticket["estado"], "En progreso")
        self.assertIn("Ingresá a Fumigaciones y subí el remito", ticket["notificaciones"][-1]["texto"])
        before_notices = len(tecman.load_notif_admin()["notificaciones"])
        self._mark_realized()
        self.assertEqual(len(tecman.load_notif_admin()["notificaciones"]), before_notices)

    def test_upload_valido_persiste_metadata_auditoria_y_notifica_admin(self):
        self._mark_realized()
        self._branch()
        response = self._upload()
        self.assertEqual(response.status_code, 302)
        ticket = self._saved()
        self.assertEqual(ticket["remito_estado"], "pendiente_validacion")
        self.assertEqual(ticket["estado"], "En progreso")
        remito = ticket["remitos_fumigacion"][0]
        self.assertEqual(remito["nombre_original"], "remito.pdf")
        self.assertEqual(remito["actor"], "Sucursal 014")
        self.assertEqual(remito["tamano"], len(b"%PDF-1.4\nfixture"))
        self.assertNotIn("remito", remito["archivo"])
        self.assertTrue((tecman.FUMIGACION_REMITOS_DIR / "920001" / remito["archivo"]).is_file())
        self.assertEqual(ticket["fumigacion_historial"][-1]["accion"], "remito_cargado")
        notice = tecman.load_notif_admin()["notificaciones"][0]
        self.assertEqual(notice["tipo"], "fumigaciones")
        self.assertEqual(notice["link"], "/admin/ticket/920001")

    def test_upload_rechazos_no_mutan_ni_dejan_huerfanos(self):
        self._mark_realized()
        self._branch()
        cases = [
            (920001, "remito.pdf", b"%PDF-1.4\nfixture", "", 400),
            (920001, "", b"", "csrf-test", 400),
            (920001, "remito.exe", b"MZfixture", "csrf-test", 400),
            (920001, "remito.pdf", b"not a pdf", "csrf-test", 400),
            (920001, "remito.png", b"%PDF-1.4\nwrong extension", "csrf-test", 400),
            (920003, "remito.pdf", b"%PDF-1.4\nfixture", "csrf-test", 404),
            (920002, "remito.pdf", b"%PDF-1.4\nfixture", "csrf-test", 403),
        ]
        for ticket_id, name, body, csrf, status in cases:
            with self.subTest(ticket=ticket_id, name=name, status=status):
                before = copy.deepcopy(tecman.load_tickets())
                before_files = sorted(str(p.relative_to(tecman.FUMIGACION_REMITOS_DIR)) for p in tecman.FUMIGACION_REMITOS_DIR.rglob("*") if p.is_file())
                response = self._upload(ticket_id, name, body, csrf)
                self.assertEqual(response.status_code, status)
                self.assertEqual(tecman.load_tickets(), before)
                after_files = sorted(str(p.relative_to(tecman.FUMIGACION_REMITOS_DIR)) for p in tecman.FUMIGACION_REMITOS_DIR.rglob("*") if p.is_file())
                self.assertEqual(after_files, before_files)

        before = copy.deepcopy(tecman.load_tickets())
        too_large = b"%PDF-" + (b"x" * tecman.FUMIGACION_REMITO_MAX_BYTES)
        self.assertEqual(self._upload(body=too_large).status_code, 400)
        self.assertEqual(tecman.load_tickets(), before)

    def test_admin_valida_y_devuelve_con_historial_y_observacion_obligatoria(self):
        self._mark_realized()
        self._branch()
        self._upload()
        remito_id = self._saved()["remito_actual_id"]
        self._admin()
        before = copy.deepcopy(self._saved())
        missing = self.client.post("/admin/ticket/920001", data={
            "_csrf_token": "csrf-test", "accion": "devolver_remito_fumigacion", "remito_id": remito_id,
        })
        self.assertEqual(missing.status_code, 400)
        self.assertEqual(self._saved(), before)

        returned = self.client.post("/admin/ticket/920001", data={
            "_csrf_token": "csrf-test", "accion": "devolver_remito_fumigacion", "remito_id": remito_id,
            "observacion": "Falta firma del aplicador",
        })
        self.assertEqual(returned.status_code, 302)
        ticket = self._saved()
        self.assertEqual(ticket["remito_estado"], "pendiente_carga")
        self.assertEqual(ticket["fumigacion_historial"][-1]["accion"], "remito_devuelto")
        self.assertIn("Falta firma", ticket["notificaciones"][-1]["texto"])
        self.assertEqual(len(ticket["remitos_fumigacion"]), 1)

        self._branch()
        self._upload(name="corregido.png", body=b"\x89PNG\r\n\x1a\nfixture")
        ticket = self._saved()
        self.assertEqual(len(ticket["remitos_fumigacion"]), 2)
        new_id = ticket["remito_actual_id"]
        self._admin()
        validated = self.client.post("/admin/ticket/920001", data={
            "_csrf_token": "csrf-test", "accion": "validar_remito_fumigacion", "remito_id": new_id,
        })
        self.assertEqual(validated.status_code, 302)
        ticket = self._saved()
        self.assertEqual(ticket["remito_estado"], "validado")
        self.assertEqual(ticket["fumigacion_historial"][-1]["accion"], "remito_validado")
        self.assertEqual(ticket["estado"], "En progreso")

    def test_archivo_solo_admin_o_sucursal_duena_y_referenciado(self):
        self._mark_realized()
        self._branch()
        self._upload()
        filename = self._saved()["remitos_fumigacion"][0]["archivo"]
        url = f"/fumigaciones/920001/remitos/{filename}"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        response.close()
        self._branch("Sucursal 020")
        self.assertEqual(self.client.get(url).status_code, 403)
        self._provider()
        self.assertEqual(self.client.get(url).status_code, 403)
        self._admin()
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        response.close()
        self.assertEqual(self.client.get("/fumigaciones/920001/remitos/no-referenciado.pdf").status_code, 404)
        self.assertIn(self.client.get("/fumigaciones/920001/remitos/%2e%2e%2fsecret.pdf").status_code, (404, 403))

    def test_compatibilidad_ticket_historico_relevado_o_con_fecha(self):
        tickets = tecman.load_tickets()
        historical = dict(self.ticket, id=920004, etapa_prov="relevado", fecha_visita="2026-08-01", notas=[])
        tickets.append(historical)
        tecman.save_tickets(tickets)
        self._branch()
        page = self.client.get("/suc/fumigaciones")
        self.assertEqual(page.status_code, 200)
        self.assertIn("920004", page.get_data(as_text=True))
        uploaded = self._upload(ticket_id=920004)
        self.assertEqual(uploaded.status_code, 302)
        saved = self._saved(920004)
        self.assertEqual(saved["remito_estado"], "pendiente_validacion")


if __name__ == "__main__":
    unittest.main()
