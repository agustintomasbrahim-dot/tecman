import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path


_TEST_ROOT = tempfile.TemporaryDirectory()
os.environ["TECMAN_DATA_DIR"] = str(Path(_TEST_ROOT.name) / "data")
os.environ["TECMAN_UPLOADS_DIR"] = str(Path(_TEST_ROOT.name) / "uploads")
os.environ.pop("DATABASE_URL", None)

import app as tecman  # noqa: E402


NOTICE = (
    "Importante: esta opción es únicamente para reportar fallas eléctricas. "
    "Si necesitás solicitar materiales o repuestos eléctricos, hacelo desde "
    "Pedido de materiales."
)


class ProblemaElectricoNoticeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.originals = {
            "tickets": tecman.TICKETS_FILE,
            "uploads": tecman.UPLOADS_DIR,
            "use_db": tecman.USE_DB,
        }
        tecman.TICKETS_FILE = root / "tickets.json"
        tecman.UPLOADS_DIR = root / "uploads"
        tecman.UPLOADS_DIR.mkdir(parents=True)
        tecman.USE_DB = False
        tecman.app.config.update(TESTING=True, SECRET_KEY="electrical-notice-test")
        tecman.save_tickets([])
        self.client = tecman.app.test_client()
        with self.client.session_transaction() as session:
            session.clear()
            session.update(
                suc_user="suc011",
                suc_nombre="Sucursal 011",
                auth_provider="entra",
                entra_role="sucursal",
                _csrf_token="csrf-test",
            )

    def tearDown(self):
        tecman.TICKETS_FILE = self.originals["tickets"]
        tecman.UPLOADS_DIR = self.originals["uploads"]
        tecman.USE_DB = self.originals["use_db"]
        self.temp.cleanup()

    def test_renderiza_texto_exacto_y_estado_inicial_accesible(self):
        body = self.client.get("/nuevo").get_data(as_text=True)
        self.assertEqual(body.count(NOTICE), 1)
        self.assertRegex(
            body,
            r'id="aviso-problema-electrico" role="status" aria-live="polite" hidden',
        )
        self.assertIn("border:1px solid #92400e", body)
        self.assertIn("background:#fffbeb;color:#78350f", body)

        preselected = self.client.get(
            "/nuevo?categoria=Problema%20El%C3%A9ctrico"
        ).get_data(as_text=True)
        opening_tag = re.search(
            r'<div id="aviso-problema-electrico"[^>]*>', preselected
        ).group(0)
        self.assertNotIn(" hidden", opening_tag)
        self.assertIn(
            '<option value="Problema Eléctrico" selected>Problema Eléctrico</option>',
            preselected,
        )

    def test_dom_muestra_y_oculta_solo_para_la_categoria_exacta(self):
        body = self.client.get("/nuevo").get_data(as_text=True)
        function = re.search(
            r"function actualizarAvisoProblemaElectrico\(categoria\) \{.*?\n\}",
            body,
            re.DOTALL,
        ).group(0)
        script = f"""
const aviso = {{hidden: true}};
const document = {{getElementById: () => aviso}};
{function}
const estados = [];
for (const categoria of ['Problema Eléctrico', 'Materiales', 'Limpieza', 'Problema Eléctrico']) {{
  actualizarAvisoProblemaElectrico(categoria);
  estados.push(aviso.hidden);
}}
process.stdout.write(JSON.stringify(estados));
"""
        result = subprocess.run(
            ["node", "-e", script],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(json.loads(result.stdout), [False, True, True, False])

    def test_error_conserva_categoria_y_aviso_en_la_recarga(self):
        with self.client.session_transaction() as session:
            session["suc_general"] = True
            session.pop("suc_nombre", None)
        response = self.client.post(
            "/nuevo",
            data={
                "_csrf_token": "csrf-test",
                "categoria": "Problema Eléctrico",
                "subcategoria": "Tablero",
                "descripcion": "Falla eléctrica",
                "solicitante_nombre": "Ana",
                "solicitante_apellido": "Sucursal",
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        opening_tag = re.search(
            r'<div id="aviso-problema-electrico"[^>]*>', body
        ).group(0)
        self.assertNotIn(" hidden", opening_tag)
        self.assertIn(
            '<option value="Problema Eléctrico" selected>Problema Eléctrico</option>',
            body,
        )
        self.assertIn('var subcategoriaParam = "Tablero";', body)
        self.assertEqual(tecman.load_tickets(), [])

    def test_post_valido_no_se_bloquea_ni_pide_confirmacion(self):
        response = self.client.post(
            "/nuevo",
            data={
                "_csrf_token": "csrf-test",
                "categoria": "Problema Eléctrico",
                "subcategoria": "Tablero",
                "descripcion": "Salta la térmica del tablero principal",
                "solicitante_nombre": "Ana",
                "solicitante_apellido": "Sucursal",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("Ticket creado", response.get_data(as_text=True))
        saved = tecman.load_tickets()
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["categoria"], "Problema Eléctrico")
        self.assertEqual(saved[0]["subcategoria"], "Tablero")


if __name__ == "__main__":
    unittest.main()
