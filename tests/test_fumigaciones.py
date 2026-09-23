import copy
import os
import tempfile
import unittest
from pathlib import Path

_TEST_ROOT = tempfile.TemporaryDirectory()
os.environ["TECMAN_DATA_DIR"] = str(Path(_TEST_ROOT.name) / "data")
os.environ["TECMAN_UPLOADS_DIR"] = str(Path(_TEST_ROOT.name) / "uploads")
os.environ.pop("DATABASE_URL", None)

import app as tecman  # noqa: E402


class FumigacionesLegacyCompatibilityTest(unittest.TestCase):
    """El circuito nuevo no usa tickets; los registros viejos siguen siendo consultables."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.original = (tecman.TICKETS_FILE, tecman.FUMIGACIONES_FILE, tecman.USE_DB)
        tecman.TICKETS_FILE = root / "tickets.json"
        tecman.FUMIGACIONES_FILE = root / "fumigaciones.json"
        tecman.USE_DB = False
        tecman.app.config.update(TESTING=True, SECRET_KEY="fumigacion-legacy-test")
        self.ticket = {
            "id": 920001,
            "sucursal": "Sucursal 014",
            "sucursal_num": "014",
            "categoria": "Mantenimiento",
            "subcategoria": "Servicio preventivo",
            "descripcion": "Control mensual histórico",
            "estado": "En progreso",
            "asignado": "Cesar Ricardo Fratini",
            "asignado_proveedor": "Cesar Ricardo Fratini",
            "etapa_prov": "relevado",
            "fumigacion_estado": "realizada",
            "remito_estado": "pendiente_carga",
            "fecha_visita": "2026-09-20",
            "creado": "2026-09-20T10:00:00",
            "actualizado": "2026-09-20T10:00:00",
            "notas": [],
        }
        tecman.save_tickets([self.ticket])
        self.client = tecman.app.test_client()

    def tearDown(self):
        tecman.TICKETS_FILE, tecman.FUMIGACIONES_FILE, tecman.USE_DB = self.original
        self.temp.cleanup()

    def provider(self):
        with self.client.session_transaction() as sess:
            sess.clear()
            sess.update(
                prov_user="frattini",
                prov_nombre="Cesar Ricardo Fratini",
                prov_tipo_cuenta="fumigacion",
                prov_session_version=1,
                _csrf_token="csrf",
            )

    def branch(self, label="Sucursal 014"):
        with self.client.session_transaction() as sess:
            sess.clear()
            sess.update(suc_user="branch", suc_nombre=label, _csrf_token="csrf")

    def test_proveedor_fumigador_no_puede_operar_ticket_historico(self):
        self.provider()
        before = copy.deepcopy(tecman.load_tickets())
        planned = self.client.post(
            "/proveedor/ticket/920001",
            data={"_csrf_token": "csrf", "accion": "planificado", "fecha_visita": "2026-10-05"},
        )
        self.assertEqual(planned.status_code, 404)
        self.assertEqual(tecman.load_tickets(), before)
        detail = self.client.get("/proveedor/ticket/920001")
        self.assertEqual(detail.status_code, 404)
        panel = self.client.get("/proveedor")
        self.assertEqual(panel.status_code, 302)
        self.assertTrue(panel.headers["Location"].endswith("/proveedor/fumigaciones"))

    def test_sucursal_conserva_consulta_del_historico_sin_crear_ticket(self):
        self.branch()
        page = self.client.get("/suc/fumigaciones")
        self.assertEqual(page.status_code, 200)
        body = page.get_data(as_text=True)
        self.assertIn("920001", body)
        self.assertIn("Pendiente de carga", body)
        self.branch("Sucursal 020")
        isolated = self.client.get("/suc/fumigaciones")
        self.assertEqual(isolated.status_code, 200)
        self.assertNotIn("920001", isolated.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
