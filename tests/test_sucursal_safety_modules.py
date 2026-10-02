import os
import tempfile
import unittest
from pathlib import Path


_TEST_ROOT = tempfile.TemporaryDirectory()
os.environ["TECMAN_DATA_DIR"] = str(Path(_TEST_ROOT.name) / "data")
os.environ["TECMAN_UPLOADS_DIR"] = str(Path(_TEST_ROOT.name) / "uploads")
os.environ.pop("DATABASE_URL", None)

import app as tecman  # noqa: E402


class SucursalSafetyModulesTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.uploads = self.root / "uploads"
        self.uploads.mkdir(parents=True)
        self.originals = {
            "HABILITACIONES_FILE": tecman.HABILITACIONES_FILE,
            "HABILITACIONES_DIR": tecman.HABILITACIONES_DIR,
            "MATAFUEGOS_FILE": tecman.MATAFUEGOS_FILE,
            "MATAFUEGOS_VISITAS_FILE": tecman.MATAFUEGOS_VISITAS_FILE,
            "SYH_FILE": tecman.SYH_FILE,
            "UPLOADS_DIR": tecman.UPLOADS_DIR,
            "PERMISOS_FILE": tecman.PERMISOS_FILE,
        }
        tecman.app.config.update(TESTING=True, SECRET_KEY="sucursal-safety-test")
        tecman.USE_DB = False
        tecman.HABILITACIONES_FILE = self.root / "habilitaciones.json"
        tecman.HABILITACIONES_DIR = self.uploads / "habilitaciones"
        tecman.HABILITACIONES_DIR.mkdir(parents=True)
        tecman.MATAFUEGOS_FILE = self.root / "matafuegos.json"
        tecman.MATAFUEGOS_VISITAS_FILE = self.root / "matafuegos_visitas.json"
        tecman.SYH_FILE = self.root / "syh.json"
        tecman.UPLOADS_DIR = self.uploads
        tecman.PERMISOS_FILE = self.root / "permisos.json"
        self.client = tecman.app.test_client()

        tecman.save_habilitaciones({"habilitaciones": [
            {
                "id": "hab-own", "sucursal": "Sucursal 014", "sucursal_num": "014",
                "numero_cert": "CERT-OWN", "municipio": "Municipio propio",
                "fecha_vencimiento": "2027-12-31", "archivo": "hab-own.pdf",
            },
            {
                "id": "hab-foreign", "sucursal": "Sucursal 020", "sucursal_num": "020",
                "numero_cert": "CERT-FOREIGN", "municipio": "Municipio ajeno",
                "fecha_vencimiento": "2027-12-31", "archivo": "hab-foreign.pdf",
            },
        ]})
        tecman.save_matafuegos({"matafuegos": [
            {
                "id": "mata-own", "sucursal": "Sucursal 014", "sucursal_num": "014",
                "tipo": "ABC PROPIO", "cantidad": 1, "ubicacion": "Salón",
                "fecha_vencimiento": "2027-12-31",
            },
            {
                "id": "mata-foreign", "sucursal": "Sucursal 020", "sucursal_num": "020",
                "tipo": "CO2 AJENO", "cantidad": 1, "ubicacion": "Depósito",
                "fecha_vencimiento": "2027-12-31",
            },
        ]})
        tecman.save_syh({
            "014": {
                "habilitacion": "Vigente",
                "documentos_detallados": [{
                    "categoria": "habilitaciones", "nombre": "Documento propio",
                    "archivo": "syh-own.pdf", "fecha": "2026-10-01",
                }],
            },
            "020": {
                "habilitacion": "Vigente",
                "documentos_detallados": [{
                    "categoria": "habilitaciones", "nombre": "Documento ajeno",
                    "archivo": "syh-foreign.pdf", "fecha": "2026-10-01",
                }],
            },
        })
        for filename in ("hab-own.pdf", "hab-foreign.pdf"):
            (tecman.HABILITACIONES_DIR / filename).write_bytes(b"%PDF-test")
        for filename in ("syh-own.pdf", "syh-foreign.pdf"):
            (self.uploads / filename).write_bytes(b"%PDF-test")
        self._branch_session("Sucursal 014")

    def tearDown(self):
        tecman.USE_DB = False
        for name, value in self.originals.items():
            setattr(tecman, name, value)
        self.temp.cleanup()

    def _branch_session(self, label, scope=None):
        with self.client.session_transaction() as session:
            session.clear()
            session["suc_user"] = "scope-test"
            session["suc_nombre"] = label
            if scope is not None:
                session["suc_general"] = True
                session["suc_scope_nums"] = scope

    def _assert_own_scope_render_and_download(self, expect_document=True):
        syh = self.client.get("/suc/syh")
        self.assertEqual(syh.status_code, 200)
        syh_html = syh.get_data(as_text=True)
        for visible in ("CERT-OWN", "ABC PROPIO"):
            self.assertIn(visible, syh_html)
        for hidden in ("CERT-FOREIGN", "Documento ajeno", "CO2 AJENO"):
            self.assertNotIn(hidden, syh_html)
        if expect_document:
            self.assertIn("Documento propio", syh_html)

        matafuegos = self.client.get("/suc/matafuegos")
        self.assertEqual(matafuegos.status_code, 200)
        mata_html = matafuegos.get_data(as_text=True)
        self.assertIn("ABC PROPIO", mata_html)
        self.assertNotIn("CO2 AJENO", mata_html)

        responses = [
            self.client.get("/uploads/habilitaciones/hab-own.pdf"),
            self.client.get("/uploads/habilitaciones/hab-foreign.pdf"),
            self.client.get("/uploads/syh/syh-own.pdf"),
            self.client.get("/uploads/syh/syh-foreign.pdf"),
        ]
        try:
            self.assertEqual([response.status_code for response in responses], [200, 404, 200, 404])
        finally:
            for response in responses:
                response.close()

    def test_branch_renders_and_downloads_only_own_safety_records(self):
        self._assert_own_scope_render_and_download()

    def test_supervisor_scope_renders_and_downloads_only_scoped_records(self):
        self._branch_session("Supervisión", scope=["014"])
        self._assert_own_scope_render_and_download(expect_document=False)


if __name__ == "__main__":
    unittest.main()
