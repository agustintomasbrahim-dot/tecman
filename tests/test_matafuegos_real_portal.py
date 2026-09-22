import copy
import io
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

PDF = b"%PDF-1.4\nreal test\n%%EOF\n"
PNG = b"\x89PNG\r\n\x1a\nreal-png"


class MatafuegosRealPortalTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.data = self.root / "data"; self.data.mkdir()
        self.uploads = self.root / "uploads"; self.uploads.mkdir()
        self.original = (tecman.TICKETS_FILE, tecman.PROVEEDOR_USERS_FILE, tecman.USE_DB)
        tecman.TICKETS_FILE = self.data / "tickets.json"
        tecman.PROVEEDOR_USERS_FILE = self.data / "proveedor_users.json"
        tecman.USE_DB = False
        self.tickets = [
            {"id": 101, "sucursal": "Sucursal 222", "descripcion": "Recarga anual", "estado": "Abierto", "asignado": "Diprogom", "notas": [{"autor": "Admin", "fecha": "2026-09-20", "texto": "Coordinar visita", "archivo": "informe.pdf"}]},
            {"id": 202, "sucursal": "Sucursal 999", "descripcion": "Control B", "estado": "Pendiente", "asignado_proveedor": "Fuego Cero"},
            {"id": 303, "sucursal": "Sucursal 111", "descripcion": "Otro rubro", "estado": "Abierto", "asignado": "CEYH"},
        ]
        tecman.TICKETS_FILE.write_text(json.dumps(self.tickets), encoding="utf-8")
        (self.uploads / "informe.pdf").write_bytes(PDF)
        tecman.PROVEEDOR_USERS_FILE.write_text(json.dumps({"users": {
            "fuego": {"password_hash": tecman._hash_password("FuegoCero-2026"), "nombre": "Fuego Cero", "tipo_cuenta": "proveedor", "proveedores": ["Fuego Cero"], "status": "active", "session_version": 1},
            "legacy_mata": {"password_hash": tecman._hash_password("LegacyMata-2026"), "nombre": "Proveedor fuera catálogo", "tipo_cuenta": "matafuegos", "proveedores": ["Proveedor fuera catálogo"], "status": "active", "session_version": 1},
        }}), encoding="utf-8")
        tecman.app.config.update(TESTING=True, SECRET_KEY="real-test", MATAFUEGOS_REAL_UPLOADS_DIR=str(self.uploads / "matafuegos_real"), MATAFUEGOS_REAL_LEGACY_UPLOADS_DIR=str(self.uploads), MATAFUEGOS_REAL_MAX_FILE_BYTES=1024 * 1024)
        self.client = tecman.app.test_client()

    def tearDown(self):
        tecman.TICKETS_FILE, tecman.PROVEEDOR_USERS_FILE, tecman.USE_DB = self.original
        self.temp.cleanup()

    def provider(self, user="diprogom", name="Diprogom", tipo="matafuegos"):
        with self.client.session_transaction() as sess:
            sess.clear(); sess.update(prov_user=user, prov_nombre=name, prov_tipo_cuenta=tipo, prov_session_version=1, _csrf_token="csrf")

    def admin(self):
        with self.client.session_transaction() as sess:
            sess.clear(); sess.update(user="admin", nombre="Administración", rol="admin", _csrf_token="csrf")

    def load(self):
        return json.loads(tecman.TICKETS_FILE.read_text(encoding="utf-8"))

    def item(self, **changes):
        data = {"_csrf_token": "csrf", "tipo": "ABC", "capacidad_kg": "5", "cantidad_unidades": "2", "ubicacion": "Salón", "identificacion": "SER-101", "encontrado": "si", "estado_fisico": "Bueno", "trabajo_realizado": "recargado", "fecha_recarga": "2026-09-22", "proximo_vencimiento": "2027-09-22", "observacion": "Sin novedad"}
        data.update(changes); return data

    def workflow(self, ticket_id=101):
        return next(t for t in self.load() if t["id"] == ticket_id)["matafuegos_portal"]

    def test_redirecciones_tipo_exacto_refresh_y_compatibilidad_custom(self):
        self.provider(tipo="proveedor")
        response = self.client.get("/proveedor")
        self.assertTrue(response.headers["Location"].endswith("/proveedor/matafuegos"))
        with self.client.session_transaction() as sess: self.assertEqual(sess["prov_tipo_cuenta"], "matafuegos")

        self.provider("fuego", "Fuego Cero", "proveedor")
        self.assertEqual(self.client.get("/proveedor/matafuegos").status_code, 200)
        with self.client.session_transaction() as sess: self.assertEqual(sess["prov_tipo_cuenta"], "matafuegos")

        self.provider("legacy_mata", "Proveedor fuera catálogo", "proveedor")
        empty = self.client.get("/proveedor/matafuegos")
        self.assertEqual(empty.status_code, 200)
        self.assertIn("No hay tickets asignados", empty.get_data(as_text=True))

        self.provider("ceyh", "CEYH", "matafuegos")
        self.assertEqual(self.client.get("/proveedor/matafuegos").status_code, 403)

    def test_panel_filtros_contadores_y_get_no_muta(self):
        before = tecman.TICKETS_FILE.read_bytes(); self.provider()
        page = self.client.get("/proveedor/matafuegos")
        body = page.get_data(as_text=True)
        self.assertEqual(page.status_code, 200); self.assertIn("TICKET #101", body); self.assertNotIn("TICKET #202", body); self.assertNotIn("TICKET #303", body)
        self.assertEqual(before, tecman.TICKETS_FILE.read_bytes())
        filtered = self.client.get("/proveedor/matafuegos?estado=Validado").get_data(as_text=True)
        self.assertIn("No hay tickets asignados en este estado", filtered)

    def test_aislamiento_panel_detalle_archivos_y_admin_separado(self):
        self.provider()
        self.assertEqual(self.client.get("/proveedor/matafuegos/ticket/202").status_code, 403)
        detail = self.client.get("/proveedor/matafuegos/ticket/101")
        self.assertEqual(detail.status_code, 200)
        self.assertIn("Coordinar visita", detail.get_data(as_text=True))
        self.assertEqual(self.client.get("/proveedor/matafuegos/ticket/101/adjunto-existente/informe.pdf").status_code, 200)
        self.assertEqual(self.client.get("/proveedor/matafuegos/ticket/202/adjunto-existente/informe.pdf").status_code, 403)
        self.assertEqual(self.client.get("/proveedor/matafuegos/ticket/101/adjunto-existente/../tickets.json").status_code, 403)
        self.admin()
        panel = self.client.get("/admin/proveedores/matafuegos").get_data(as_text=True)
        self.assertIn("TICKET #101", panel); self.assertIn("TICKET #202", panel); self.assertNotIn("TICKET #303", panel)
        self.assertEqual(self.client.get("/admin/proveedores/matafuegos/ticket/303").status_code, 404)

    def test_todos_los_post_requieren_csrf_sin_mutacion(self):
        self.provider(); before = tecman.TICKETS_FILE.read_bytes()
        routes = [
            ("/proveedor/matafuegos/ticket/101/programar", {}),
            ("/proveedor/matafuegos/ticket/101/matafuegos", self.item(_csrf_token="")),
            ("/proveedor/matafuegos/ticket/101/finalizar", {}),
        ]
        for path, data in routes:
            with self.subTest(path=path): self.assertEqual(self.client.post(path, data=data).status_code, 400)
        self.admin()
        self.assertEqual(self.client.post("/admin/proveedores/matafuegos/ticket/101/validar").status_code, 400)
        self.assertEqual(before, tecman.TICKETS_FILE.read_bytes())

    def test_flujo_completo_devolucion_auditoria_y_estado_historico_intacto(self):
        self.provider()
        self.assertEqual(self.client.post("/proveedor/matafuegos/ticket/101/programar", data={"_csrf_token": "csrf", "fecha_programada": "2026-09-23"}).status_code, 302)
        add = self.client.post("/proveedor/matafuegos/ticket/101/matafuegos", data={**self.item(), "foto_antes": (io.BytesIO(PNG), "antes.png")}, content_type="multipart/form-data")
        self.assertEqual(add.status_code, 302)
        item_id = self.workflow()["matafuegos"][0]["id"]
        edit = self.client.post(f"/proveedor/matafuegos/ticket/101/matafuegos/{item_id}", data={**self.item(ubicacion="Depósito"), "foto_despues": (io.BytesIO(PNG), "despues.png")}, content_type="multipart/form-data")
        self.assertEqual(edit.status_code, 302)
        complete = self.client.post("/proveedor/matafuegos/ticket/101/finalizar", data={"_csrf_token": "csrf", "remito": (io.BytesIO(PDF), "remito.pdf"), "certificado": (io.BytesIO(PDF), "certificado.pdf")}, content_type="multipart/form-data")
        self.assertEqual(complete.status_code, 302); self.assertEqual(self.workflow()["estado"], "Realizado")
        self.assertEqual(next(t for t in self.load() if t["id"] == 101)["estado"], "Abierto")

        self.admin()
        returned = self.client.post("/admin/proveedores/matafuegos/ticket/101/devolver", data={"_csrf_token": "csrf", "observacion": "Corregir identificación"})
        self.assertEqual(returned.status_code, 302); self.assertEqual(self.workflow()["estado"], "Pendiente")
        self.assertEqual(self.workflow()["observacion_devolucion"], "Corregir identificación")
        actions = [h["accion"] for h in self.workflow()["historial"]]
        self.assertEqual(actions, ["Programado", "Matafuego agregado", "Matafuego editado", "Realizado", "Devuelto para corregir"])

    def test_anulacion_no_borra_y_validado_bloquea_edicion(self):
        self.provider()
        self.client.post("/proveedor/matafuegos/ticket/101/programar", data={"_csrf_token": "csrf", "fecha_programada": "2026-09-23"})
        self.client.post("/proveedor/matafuegos/ticket/101/matafuegos", data=self.item())
        item_id = self.workflow()["matafuegos"][0]["id"]
        self.client.post(f"/proveedor/matafuegos/ticket/101/matafuegos/{item_id}/anular", data={"_csrf_token": "csrf", "motivo": "Equipo retirado"})
        self.assertFalse(self.workflow()["matafuegos"][0]["activo"])
        self.assertEqual(self.workflow()["matafuegos"][0]["anulado_motivo"], "Equipo retirado")

        data = self.load(); wf = next(t for t in data if t["id"] == 101)["matafuegos_portal"]
        wf["matafuegos"][0]["activo"] = True; wf["estado"] = "Realizado"; tecman.TICKETS_FILE.write_text(json.dumps(data), encoding="utf-8")
        self.admin(); self.client.post("/admin/proveedores/matafuegos/ticket/101/validar", data={"_csrf_token": "csrf"})
        self.assertEqual(self.workflow()["estado"], "Validado")
        self.provider(); before = copy.deepcopy(self.workflow())
        self.client.post(f"/proveedor/matafuegos/ticket/101/matafuegos/{item_id}", data=self.item(ubicacion="No debe guardar"))
        self.assertEqual(before, self.workflow())

    def test_validaciones_fechas_campos_firmas_limites_y_nombres_aleatorios(self):
        self.provider()
        self.client.post("/proveedor/matafuegos/ticket/101/programar", data={"_csrf_token": "csrf", "fecha_programada": "2026-09-23"})
        invalids = [
            self.item(tipo="Inventado"), self.item(cantidad_unidades="0"), self.item(fecha_recarga="2027-01-01", proximo_vencimiento="2026-01-01"), self.item(identificacion="=FORMULA")
        ]
        for payload in invalids:
            before = copy.deepcopy(self.workflow()); self.client.post("/proveedor/matafuegos/ticket/101/matafuegos", data=payload); self.assertEqual(before, self.workflow())
        bad = self.client.post("/proveedor/matafuegos/ticket/101/matafuegos", data={**self.item(), "foto_antes": (io.BytesIO(b"not png"), "fraude.png")}, content_type="multipart/form-data")
        self.assertEqual(bad.status_code, 302); self.assertEqual([], self.workflow()["matafuegos"])
        extension = self.client.post("/proveedor/matafuegos/ticket/101/matafuegos", data={**self.item(), "foto_antes": (io.BytesIO(PNG), "foto.exe")}, content_type="multipart/form-data")
        self.assertEqual(extension.status_code, 302); self.assertEqual([], self.workflow()["matafuegos"])
        tecman.app.config["MATAFUEGOS_REAL_MAX_FILE_BYTES"] = 12
        oversized = self.client.post("/proveedor/matafuegos/ticket/101/matafuegos", data={**self.item(), "foto_antes": (io.BytesIO(PNG + b"oversized"), "grande.png")}, content_type="multipart/form-data")
        self.assertEqual(oversized.status_code, 302); self.assertEqual([], self.workflow()["matafuegos"])
        tecman.app.config["MATAFUEGOS_REAL_MAX_FILE_BYTES"] = 1024 * 1024
        self.client.post("/proveedor/matafuegos/ticket/101/matafuegos", data={**self.item(), "foto_antes": (io.BytesIO(PNG), "real.png")}, content_type="multipart/form-data")
        name = self.workflow()["matafuegos"][0]["fotos_antes"][0]["archivo"]
        self.assertRegex(name, r"^[a-f0-9]{32}\.png$"); self.assertNotIn("real", name)

    def test_finalizacion_atomica_documentos_y_archivo_protegido(self):
        self.provider(); self.client.post("/proveedor/matafuegos/ticket/101/programar", data={"_csrf_token": "csrf", "fecha_programada": "2026-09-23"}); self.client.post("/proveedor/matafuegos/ticket/101/matafuegos", data=self.item())
        before = copy.deepcopy(self.workflow())
        self.client.post("/proveedor/matafuegos/ticket/101/finalizar", data={"_csrf_token": "csrf", "remito": (io.BytesIO(PDF), "remito.pdf"), "certificado": (io.BytesIO(b"fake"), "certificado.pdf")}, content_type="multipart/form-data")
        self.assertEqual(before, self.workflow())
        self.client.post("/proveedor/matafuegos/ticket/101/finalizar", data={"_csrf_token": "csrf", "remito": (io.BytesIO(PDF), "remito.pdf"), "certificado": (io.BytesIO(PDF), "certificado.pdf")}, content_type="multipart/form-data")
        filename = self.workflow()["documentos"]["remito"]["archivo"]
        self.assertEqual(self.client.get(f"/proveedor/matafuegos/ticket/101/archivo/{filename}").status_code, 200)
        self.assertEqual(self.client.get(f"/static/uploads/matafuegos_real/101/{filename}").status_code, 404)
        self.provider("fuego", "Fuego Cero", "proveedor")
        self.assertEqual(self.client.get(f"/proveedor/matafuegos/ticket/101/archivo/{filename}").status_code, 403)
        self.assertEqual(self.client.get(f"/static/uploads/matafuegos_real/101/{filename}").status_code, 404)
        before = tecman.TICKETS_FILE.read_bytes()
        denied = self.client.post("/proveedor/matafuegos/ticket/101/programar", data={"_csrf_token": "csrf", "fecha_programada": "2026-09-24"})
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(before, tecman.TICKETS_FILE.read_bytes())
