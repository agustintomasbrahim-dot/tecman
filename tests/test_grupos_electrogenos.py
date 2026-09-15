import io
import os
import tempfile
import unittest

_TEST_DATA = tempfile.TemporaryDirectory()
os.environ["TECMAN_DATA_DIR"] = _TEST_DATA.name
os.environ["TECMAN_UPLOADS_DIR"] = os.path.join(_TEST_DATA.name, "uploads")
os.environ.pop("DATABASE_URL", None)

import app as tecman  # noqa: E402


class GruposElectrogenosTest(unittest.TestCase):
    def setUp(self):
        tecman.app.config.update(TESTING=True, SECRET_KEY="test-only")
        tecman.USE_DB = False
        tecman.GRUPOS_ELECTROGENOS_FILE = tecman.Path(_TEST_DATA.name) / "grupos_electrogenos.json"
        tecman.NOTIF_ADMIN_FILE = tecman.Path(_TEST_DATA.name) / "notif_admin.json"
        for path in (tecman.GRUPOS_ELECTROGENOS_FILE, tecman.NOTIF_ADMIN_FILE):
            if path.exists():
                path.unlink()
        self.client = tecman.app.test_client()

    def _admin_session(self):
        with self.client.session_transaction() as sess:
            sess["user"] = "agustin"
            sess["nombre"] = "Admin Test"
            sess["rol"] = "admin"
            sess["_csrf_token"] = "csrf-test"

    def _sucursal_session(self, label):
        with self.client.session_transaction() as sess:
            sess.clear()
            sess["suc_user"] = "test"
            sess["suc_nombre"] = label
            sess["_csrf_token"] = "csrf-test"

    def test_admin_manual_csv_and_empty_template(self):
        self._admin_session()
        suc1, suc2 = tecman.SUCURSALES[:2]
        response = self.client.post("/admin/grupos-electrogenos", data={
            "_csrf_token": "csrf-test", "sucursal": suc1, "marca": "Marca A",
            "modelo": "Modelo 1", "numero_serie": "SER-1", "potencia": "50 kVA",
        })
        self.assertEqual(response.status_code, 302)

        csv_data = (
            "sucursal,marca,modelo,potencia,numero de serie,combustible,ubicacion,estado,ultima revision,proximo mantenimiento,proveedor,observaciones\n"
            f"{suc2},Marca B,Modelo 2,80 kVA,SER-2,Diesel,Patio,Operativo,2026-01-01,2026-10-01,Proveedor,\n"
        ).encode()
        response = self.client.post("/admin/grupos-electrogenos/importar", data={
            "_csrf_token": "csrf-test", "archivo": (io.BytesIO(csv_data), "equipos.csv")
        }, content_type="multipart/form-data")
        self.assertEqual(response.status_code, 302)
        items = tecman.load_grupos_electrogenos()["grupos_electrogenos"]
        self.assertEqual(len(items), 2)
        self.assertTrue(all(x["estado_validacion"] == "pendiente_validacion" for x in items))
        self.assertTrue(all(x["historial"] for x in items))
        self.assertEqual(len(tecman.load_notif_admin()["notificaciones"]), 2)

        response = self.client.get("/admin/grupos-electrogenos/plantilla.xlsx")
        self.assertEqual(response.status_code, 200)
        from openpyxl import load_workbook
        workbook = load_workbook(io.BytesIO(response.data), read_only=True)
        rows = list(workbook.active.iter_rows(values_only=True))
        workbook.close()
        self.assertEqual(len(rows), 1)
        self.assertEqual(tuple(rows[0]), tecman.GENERADOR_IMPORT_HEADERS)

    def test_import_is_atomic_on_invalid_branch(self):
        self._admin_session()
        suc = tecman.SUCURSALES[0]
        csv_data = f"sucursal,marca\n{suc},OK\nSucursal inexistente,Error\n".encode()
        response = self.client.post("/admin/grupos-electrogenos/importar", data={
            "_csrf_token": "csrf-test", "archivo": (io.BytesIO(csv_data), "equipos.csv")
        }, content_type="multipart/form-data")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(tecman.load_grupos_electrogenos()["grupos_electrogenos"], [])

    def test_branch_isolation_and_audited_validation(self):
        suc1, suc2 = tecman.SUCURSALES[:2]
        with tecman.app.test_request_context("/"):
            one = tecman._generador_from_values({"sucursal": suc1, "marca": "Visible"}, "Admin", "test")
            two = tecman._generador_from_values({"sucursal": suc2, "marca": "Oculto"}, "Admin", "test")
        tecman.save_grupos_electrogenos({"grupos_electrogenos": [one, two]})
        self._sucursal_session(suc1)

        response = self.client.get("/suc/grupos-electrogenos")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Visible", response.data)
        self.assertNotIn(b"Oculto", response.data)

        forbidden = self.client.post(f"/suc/grupos-electrogenos/{two['id']}/validar", data={
            "_csrf_token": "csrf-test", "accion": "confirmar"
        })
        self.assertEqual(forbidden.status_code, 404)

        confirmed = self.client.post(f"/suc/grupos-electrogenos/{one['id']}/validar", data={
            "_csrf_token": "csrf-test", "accion": "confirmar"
        })
        self.assertEqual(confirmed.status_code, 302)
        saved = tecman.load_grupos_electrogenos()["grupos_electrogenos"]
        self.assertEqual(next(x for x in saved if x["id"] == one["id"])["estado_validacion"], "validado")

        accepted = self.client.post(f"/suc/grupos-electrogenos/{one['id']}/validar", data={
            "_csrf_token": "csrf-test", "accion": "diferencias", "diferencias": "Serie no coincide"
        })
        self.assertEqual(accepted.status_code, 302)
        saved = tecman.load_grupos_electrogenos()["grupos_electrogenos"]
        current = next(x for x in saved if x["id"] == one["id"])
        untouched = next(x for x in saved if x["id"] == two["id"])
        self.assertEqual(current["estado_validacion"], "con_diferencias")
        self.assertEqual(current["historial"][-1]["accion"], "diferencias_informadas")
        self.assertEqual(untouched["estado_validacion"], "pendiente_validacion")

    def test_xlsx_import(self):
        self._admin_session()
        from openpyxl import Workbook
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(list(tecman.GENERADOR_IMPORT_HEADERS))
        sheet.append([tecman.SUCURSALES[0], "Marca XLSX", "Modelo XLSX", "30 kVA", "SER-XLSX", "Gas", "Exterior", "Reserva", "2026-01-01", "2027-01-01", "Proveedor", ""])
        output = io.BytesIO()
        workbook.save(output)
        workbook.close()
        output.seek(0)
        response = self.client.post("/admin/grupos-electrogenos/importar", data={
            "_csrf_token": "csrf-test", "archivo": (output, "equipos.xlsx")
        }, content_type="multipart/form-data")
        self.assertEqual(response.status_code, 302)
        items = tecman.load_grupos_electrogenos()["grupos_electrogenos"]
        self.assertEqual(items[0]["numero_serie"], "SER-XLSX")

    def test_routes_are_protected(self):
        self.assertEqual(self.client.get("/admin/grupos-electrogenos").status_code, 302)
        self.assertEqual(self.client.get("/suc/grupos-electrogenos").status_code, 302)

    def test_post_requires_csrf(self):
        self._admin_session()
        response = self.client.post("/admin/grupos-electrogenos", data={"sucursal": tecman.SUCURSALES[0]})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(tecman.load_grupos_electrogenos()["grupos_electrogenos"], [])


if __name__ == "__main__":
    unittest.main()
