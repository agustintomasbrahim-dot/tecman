import copy
import hashlib
import io
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
import matafuegos_demo as demo  # noqa: E402


PDF_BYTES = b"%PDF-1.4\n% DEMO TEST\n%%EOF\n"
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"demo-png"


class MatafuegosDemoPortalTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.data_file = self.root / "data" / "matafuegos_demo.json"
        self.uploads_dir = self.root / "data" / "matafuegos_demo_uploads"
        self.real_files = {
            "tickets": self.root / "data" / "tickets.json",
            "matafuegos": self.root / "data" / "matafuegos.json",
            "notificaciones": self.root / "data" / "notif_admin.json",
        }
        for name, path in self.real_files.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"marker": name, "formula": "=NO-TOCAR"}), encoding="utf-8")
        self.real_hashes = self._hashes(self.real_files.values())

        tecman.app.config.update(
            TESTING=True,
            SECRET_KEY="test-only",
            MATAFUEGOS_DEMO_DATA_FILE=str(self.data_file),
            MATAFUEGOS_DEMO_UPLOADS_DIR=str(self.uploads_dir),
        )
        tecman.USE_DB = False
        tecman.TICKETS_FILE = self.real_files["tickets"]
        tecman.MATAFUEGOS_FILE = self.real_files["matafuegos"]
        tecman.NOTIF_ADMIN_FILE = self.real_files["notificaciones"]
        self.client = tecman.app.test_client()

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def _hashes(paths):
        return {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}

    def _load(self):
        with tecman.app.app_context():
            return demo.load_demo_data()

    def _save(self, data):
        with tecman.app.app_context():
            demo.save_demo_data(data)

    def _demo_session(self):
        with self.client.session_transaction() as sess:
            sess.clear()
            sess["prov_user"] = "matafuegos_demo"
            sess["prov_nombre"] = "Demo Matafuegos"
            sess["prov_tipo_cuenta"] = "matafuegos_demo"
            sess["_csrf_token"] = "csrf-test"

    def _admin_session(self):
        with self.client.session_transaction() as sess:
            sess.clear()
            sess["user"] = "admin-test"
            sess["nombre"] = "Admin Demo"
            sess["rol"] = "admin"
            sess["_csrf_token"] = "csrf-test"

    def _real_provider_session(self):
        with self.client.session_transaction() as sess:
            sess.clear()
            sess["prov_user"] = "diprogom"
            sess["prov_nombre"] = "Diprogom"
            sess["prov_tipo_cuenta"] = "matafuegos"
            sess["_csrf_token"] = "csrf-test"

    @staticmethod
    def _valid_item(**overrides):
        payload = {
            "_csrf_token": "csrf-test",
            "tipo": "ABC",
            "capacidad_kg": "2,5",
            "cantidad_unidades": "3",
            "ubicacion": "Sector Demo",
            "identificacion": "SERIE-DEMO-NUEVA",
            "encontrado": "si",
            "estado_fisico": "Bueno",
            "trabajo_realizado": "recargado",
            "fecha_recarga": "2026-09-22",
            "proximo_vencimiento": "2027-09-22",
            "observacion": "Sólo datos ficticios",
        }
        payload.update(overrides)
        return payload

    def _order(self, order_id):
        return next(order for order in self._load()["ordenes"] if order["id"] == order_id)

    def test_login_demo_usa_env_o_fallback_y_redirige_sin_aliases(self):
        account = tecman.DEFAULT_PROVEEDOR_USERS["matafuegos_demo"]
        self.assertEqual(account["nombre"], "Demo Matafuegos")
        self.assertEqual(account["tipo_cuenta"], "matafuegos_demo")
        self.assertEqual(account["proveedores"], [])
        self.assertEqual(account["password"], os.environ.get("MATAFUEGOS_DEMO_PASSWORD") or tecman._PROVEEDOR_PWD)
        self.assertEqual(tecman.DEFAULT_PROVEEDOR_USERS["diprogom"]["nombre"], "Diprogom")
        self.assertEqual(tecman.DEFAULT_PROVEEDOR_USERS["diprogom"]["tipo_cuenta"], "matafuegos")

        custom_users = self.root / "data" / "proveedor_users.json"
        custom_users.write_text(json.dumps({"users": {"matafuegos_demo": {"password": account["password"], "nombre": "Real", "tipo_cuenta": "proveedor", "proveedores": ["Diprogom"]}}}), encoding="utf-8")
        with patch.object(tecman, "PROVEEDOR_USERS_FILE", custom_users):
            protected_account = tecman.load_proveedor_users()["matafuegos_demo"]
        self.assertEqual(protected_account, account)

        login_page = self.client.get("/proveedor/login")
        self.assertEqual(login_page.status_code, 200)
        with self.client.session_transaction() as sess:
            csrf = sess["_csrf_token"]
        response = self.client.post(
            "/proveedor/login",
            data={"_csrf_token": csrf, "usuario": "matafuegos_demo", "password": account["password"]},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/proveedor/matafuegos-demo"))
        with self.client.session_transaction() as sess:
            self.assertEqual(sess["prov_tipo_cuenta"], "matafuegos_demo")
        self.assertTrue(self.client.get("/proveedor").headers["Location"].endswith("/proveedor/matafuegos-demo"))

    def test_login_post_requiere_csrf(self):
        response = self.client.post(
            "/proveedor/login",
            data={"usuario": "matafuegos_demo", "password": tecman.DEFAULT_PROVEEDOR_USERS["matafuegos_demo"]["password"]},
        )
        self.assertEqual(response.status_code, 400)
        with self.client.session_transaction() as sess:
            self.assertNotIn("prov_user", sess)

    def test_seed_es_idempotente_ficticio_y_no_toca_runtime_real(self):
        first = self._load()
        first_bytes = self.data_file.read_bytes()
        second = self._load()
        self.assertEqual(first, second)
        self.assertEqual(first_bytes, self.data_file.read_bytes())
        self.assertEqual(len(first["ordenes"]), 3)
        self.assertEqual({order["estado"] for order in first["ordenes"]}, {"Pendiente", "Programado", "Realizado"})
        self.assertTrue(all(order["demo"] for order in first["ordenes"]))
        self.assertTrue(all(order["sucursal"].startswith("Sucursal Demo ") for order in first["ordenes"]))
        serialized = json.dumps(first, ensure_ascii=False)
        self.assertNotIn("Diprogom", serialized)
        self.assertEqual(self._hashes(self.real_files.values()), self.real_hashes)

    def test_permisos_cruzados_y_rutas_dedicadas(self):
        anonymous = self.client.get("/proveedor/matafuegos-demo")
        self.assertEqual(anonymous.status_code, 302)
        self.assertIn(anonymous.headers["Location"], ("/proveedor/login", "/proveedores/login"))

        with self.client.session_transaction() as sess:
            sess.clear()
            sess["suc_user"] = "sucursal-demo"
        branch = self.client.get("/proveedor/matafuegos-demo")
        self.assertEqual(branch.status_code, 302)

        self._real_provider_session()
        self.assertEqual(self.client.get("/proveedor/matafuegos-demo").status_code, 403)
        self.assertEqual(self.client.get("/admin/matafuegos-demo").status_code, 302)

        self._demo_session()
        self.assertEqual(self.client.get("/proveedor/matafuegos-demo").status_code, 200)
        self.assertEqual(self.client.get("/admin/matafuegos-demo").status_code, 302)
        # El redirect administrativo limpia la sesión ajena; reabrimos la sesión demo.
        self._demo_session()
        # Sin aliases/proveedores reales, una cuenta demo no puede abrir tickets reales.
        tecman.TICKETS_FILE.write_text(json.dumps([{"id": 77, "asignado": "Diprogom", "sucursal": "Sucursal 222"}]), encoding="utf-8")
        self.assertEqual(self.client.get("/proveedor/ticket/77").status_code, 403)

        self._admin_session()
        admin_page = self.client.get("/admin/matafuegos-demo")
        self.assertEqual(admin_page.status_code, 200)
        self.assertIn("Previsualización administrativa", admin_page.get_data(as_text=True))
        providers_page = self.client.get("/admin/proveedores")
        providers_text = providers_page.get_data(as_text=True)
        self.assertEqual(providers_page.status_code, 200)
        self.assertIn("Demo portal matafuegos", providers_text)
        self.assertNotIn(tecman.DEFAULT_PROVEEDOR_USERS["matafuegos_demo"]["password"], providers_text)

    def test_panel_y_detalle_renderizan_marca_demo_cuatro_estados_y_csrf(self):
        self._demo_session()
        panel = self.client.get("/proveedor/matafuegos-demo")
        text = panel.get_data(as_text=True)
        self.assertEqual(panel.status_code, 200)
        self.assertIn("DATOS FICTICIOS", text)
        for state in demo.DEMO_STATES:
            self.assertIn(state, text)
        detail = self.client.get("/proveedor/matafuegos-demo/orden/DEMO-002")
        detail_text = detail.get_data(as_text=True)
        self.assertEqual(detail.status_code, 200)
        self.assertIn("Datos completamente ficticios", detail_text)
        self.assertIn('name="_csrf_token" value="csrf-test"', detail_text)
        self.assertIn("Capacidad (kg)", detail_text)
        self.assertIn("Cantidad de unidades", detail_text)
        self.assertIn("Anular sin borrar", detail_text)

    def test_programacion_valida_y_rechaza_saltos_sin_mutar(self):
        self._demo_session()
        today = demo.dt.date.today().isoformat()
        response = self.client.post(
            "/proveedor/matafuegos-demo/orden/DEMO-001/programar",
            data={"_csrf_token": "csrf-test", "fecha_programada": today},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self._order("DEMO-001")["estado"], "Programado")

        before = copy.deepcopy(self._load())
        past = (demo.dt.date.today() - demo.dt.timedelta(days=1)).isoformat()
        self.client.post(
            "/proveedor/matafuegos-demo/orden/DEMO-001/programar",
            data={"_csrf_token": "csrf-test", "fecha_programada": past},
        )
        self.assertEqual(self._load(), before)

        invalid_csrf = self.client.post(
            "/proveedor/matafuegos-demo/orden/DEMO-001/programar",
            data={"_csrf_token": "incorrecto", "fecha_programada": today},
        )
        self.assertEqual(invalid_csrf.status_code, 400)
        self.assertEqual(self._load(), before)

    def test_kg_decimal_y_cantidad_separados_con_validaciones(self):
        self._demo_session()
        response = self.client.post(
            "/proveedor/matafuegos-demo/orden/DEMO-001/matafuegos",
            data=self._valid_item(),
        )
        self.assertEqual(response.status_code, 302)
        item = self._order("DEMO-001")["matafuegos"][0]
        self.assertEqual(item["capacidad_kg"], "2.5")
        self.assertEqual(item["cantidad_unidades"], 3)

        for field, value in (
            ("capacidad_kg", "0"),
            ("capacidad_kg", "-2.5"),
            ("capacidad_kg", "abc"),
            ("capacidad_kg", "2.555"),
            ("cantidad_unidades", "0"),
            ("cantidad_unidades", "-1"),
            ("cantidad_unidades", "2.5"),
            ("observacion", "=HYPERLINK(\"https://example.invalid\")"),
        ):
            with self.subTest(field=field, value=value):
                before = copy.deepcopy(self._load())
                self.client.post(
                    "/proveedor/matafuegos-demo/orden/DEMO-001/matafuegos",
                    data=self._valid_item(**{field: value, "identificacion": f"INVALID-{field}-{value}"}),
                )
                self.assertEqual(self._load(), before)

    def test_anulacion_con_motivo_no_elimina_y_exige_activo_para_finalizar(self):
        self._demo_session()
        order = self._order("DEMO-002")
        item_id = order["matafuegos"][0]["id"]
        before = copy.deepcopy(self._load())
        self.client.post(
            f"/proveedor/matafuegos-demo/orden/DEMO-002/matafuegos/{item_id}/anular",
            data={"_csrf_token": "csrf-test", "motivo": ""},
        )
        self.assertEqual(self._load(), before)

        self.client.post(
            f"/proveedor/matafuegos-demo/orden/DEMO-002/matafuegos/{item_id}/anular",
            data={"_csrf_token": "csrf-test", "motivo": "Equipo ficticio duplicado"},
        )
        item = self._order("DEMO-002")["matafuegos"][0]
        self.assertFalse(item["activo"])
        self.assertEqual(item["anulado_motivo"], "Equipo ficticio duplicado")
        before = copy.deepcopy(self._load())
        self.client.post(
            "/proveedor/matafuegos-demo/orden/DEMO-002/finalizar",
            data={
                "_csrf_token": "csrf-test",
                "remito": (io.BytesIO(PDF_BYTES), "remito.pdf"),
                "certificado": (io.BytesIO(PDF_BYTES), "certificado.pdf"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(self._load(), before)
        self.assertFalse(self.uploads_dir.exists())

    def test_finalizacion_exige_campos_fechas_y_documentos_y_es_atomica_en_fallos(self):
        self._demo_session()
        before = copy.deepcopy(self._load())
        self.client.post(
            "/proveedor/matafuegos-demo/orden/DEMO-002/finalizar",
            data={"_csrf_token": "csrf-test"},
        )
        self.assertEqual(self._load(), before)

        item_id = self._order("DEMO-002")["matafuegos"][0]["id"]
        invalid_dates = self._valid_item(
            identificacion="SERIE-DEMO-002",
            proximo_vencimiento="2026-09-22",
        )
        before = copy.deepcopy(self._load())
        self.client.post(
            f"/proveedor/matafuegos-demo/orden/DEMO-002/matafuegos/{item_id}",
            data=invalid_dates,
        )
        self.assertEqual(self._load(), before)

        response = self.client.post(
            "/proveedor/matafuegos-demo/orden/DEMO-002/finalizar",
            data={
                "_csrf_token": "csrf-test",
                "remito": (io.BytesIO(PDF_BYTES), "remito_demo.pdf"),
                "certificado": (io.BytesIO(PDF_BYTES), "certificado_demo.pdf"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 302)
        order = self._order("DEMO-002")
        self.assertEqual(order["estado"], "Realizado")
        self.assertEqual(set(order["documentos"]), {"remito", "certificado"})
        self.assertEqual(len(list(self.uploads_dir.iterdir())), 2)
        self.assertEqual(self._hashes(self.real_files.values()), self.real_hashes)

    def test_uploads_seguros_y_sin_mutacion_ante_fallo(self):
        self._demo_session()
        for file_tuple in (
            (io.BytesIO(PDF_BYTES), "../../escape.pdf"),
            (io.BytesIO(b"not-a-png"), "foto.png"),
            (io.BytesIO(PNG_BYTES), "foto.svg"),
        ):
            with self.subTest(filename=file_tuple[1]):
                before = copy.deepcopy(self._load())
                payload = self._valid_item(identificacion=f"UPLOAD-{file_tuple[1]}")
                payload["foto_antes"] = file_tuple
                self.client.post(
                    "/proveedor/matafuegos-demo/orden/DEMO-001/matafuegos",
                    data=payload,
                    content_type="multipart/form-data",
                )
                self.assertEqual(self._load(), before)
                self.assertFalse(self.uploads_dir.exists() and any(self.uploads_dir.iterdir()))

        before = copy.deepcopy(self._load())
        original_limit = tecman.app.config["MAX_CONTENT_LENGTH"]
        tecman.app.config["MAX_CONTENT_LENGTH"] = 32
        try:
            too_large = self._valid_item(identificacion="ARCHIVO-GRANDE")
            too_large["foto_antes"] = (io.BytesIO(PNG_BYTES + b"x" * 64), "grande.png")
            response = self.client.post(
                "/proveedor/matafuegos-demo/orden/DEMO-001/matafuegos",
                data=too_large,
                content_type="multipart/form-data",
            )
        finally:
            tecman.app.config["MAX_CONTENT_LENGTH"] = original_limit
        self.assertEqual(response.status_code, 413)
        self.assertEqual(self._load(), before)

        payload = self._valid_item(identificacion="CON-FOTO")
        payload["foto_antes"] = (io.BytesIO(PNG_BYTES), "antes demo.png")
        self.client.post(
            "/proveedor/matafuegos-demo/orden/DEMO-001/matafuegos",
            data=payload,
            content_type="multipart/form-data",
        )
        filename = self._order("DEMO-001")["matafuegos"][0]["fotos_antes"][0]["archivo"]
        self.assertRegex(filename, r"^demo_[a-f0-9]{32}\.png$")
        self.assertNotIn("antes", filename)
        file_response = self.client.get(f"/matafuegos-demo/archivo/{filename}")
        self.assertEqual(file_response.status_code, 200)
        file_response.close()
        self._real_provider_session()
        self.assertEqual(self.client.get(f"/matafuegos-demo/archivo/{filename}").status_code, 403)

    def test_admin_devolucion_obligatoria_reprogramacion_y_revalidacion(self):
        self._admin_session()
        before = copy.deepcopy(self._load())
        self.client.post(
            "/admin/matafuegos-demo/orden/DEMO-003/devolver",
            data={"_csrf_token": "csrf-test", "observacion": "   "},
        )
        self.assertEqual(self._load(), before)

        self.client.post(
            "/admin/matafuegos-demo/orden/DEMO-003/devolver",
            data={"_csrf_token": "csrf-test", "observacion": "Corregir identificación ficticia"},
        )
        returned = self._order("DEMO-003")
        self.assertEqual(returned["estado"], "Pendiente")
        self.assertEqual(returned["observacion_devolucion"], "Corregir identificación ficticia")
        self.assertEqual(returned["historial"][-1]["accion"], "Devuelto para corregir")

        self._demo_session()
        today = demo.dt.date.today().isoformat()
        self.client.post(
            "/proveedor/matafuegos-demo/orden/DEMO-003/programar",
            data={"_csrf_token": "csrf-test", "fecha_programada": today},
        )
        self.client.post(
            "/proveedor/matafuegos-demo/orden/DEMO-003/finalizar",
            data={
                "_csrf_token": "csrf-test",
                "remito": (io.BytesIO(PDF_BYTES), "nuevo_remito.pdf"),
                "certificado": (io.BytesIO(PDF_BYTES), "nuevo_certificado.pdf"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(self._order("DEMO-003")["estado"], "Realizado")

        self._admin_session()
        self.client.post(
            "/admin/matafuegos-demo/orden/DEMO-003/validar",
            data={"_csrf_token": "csrf-test"},
        )
        validated = self._order("DEMO-003")
        self.assertEqual(validated["estado"], "Validado")
        self.assertEqual(validated["historial"][-1]["accion"], "Validado")

        # Una orden Validada no admite cambios de relevamiento ni documentación.
        self._demo_session()
        before = copy.deepcopy(self._load())
        item_id = validated["matafuegos"][0]["id"]
        self.client.post(
            f"/proveedor/matafuegos-demo/orden/DEMO-003/matafuegos/{item_id}",
            data=self._valid_item(identificacion="INTENTO-POST-VALIDACION"),
        )
        self.client.post(
            "/proveedor/matafuegos-demo/orden/DEMO-003/finalizar",
            data={
                "_csrf_token": "csrf-test",
                "remito": (io.BytesIO(PDF_BYTES), "otro.pdf"),
                "certificado": (io.BytesIO(PDF_BYTES), "otro2.pdf"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(self._load(), before)

    def test_ids_manipulados_y_transiciones_invalidas_no_mutan(self):
        self._demo_session()
        before = copy.deepcopy(self._load())
        missing = self.client.post(
            "/proveedor/matafuegos-demo/orden/REAL-999/programar",
            data={"_csrf_token": "csrf-test", "fecha_programada": demo.dt.date.today().isoformat()},
        )
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(self._load(), before)

        # Pendiente no puede saltar directamente a Realizado.
        self.client.post(
            "/proveedor/matafuegos-demo/orden/DEMO-001/finalizar",
            data={
                "_csrf_token": "csrf-test",
                "remito": (io.BytesIO(PDF_BYTES), "remito.pdf"),
                "certificado": (io.BytesIO(PDF_BYTES), "certificado.pdf"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(self._load(), before)

        self._admin_session()
        self.client.post(
            "/admin/matafuegos-demo/orden/DEMO-001/validar",
            data={"_csrf_token": "csrf-test"},
        )
        self.assertEqual(self._load(), before)


if __name__ == "__main__":
    unittest.main()
