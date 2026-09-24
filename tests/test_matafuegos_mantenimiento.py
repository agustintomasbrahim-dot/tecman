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


class MatafuegosMantenimientoTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        tecman.app.config.update(TESTING=True, SECRET_KEY="test-only")
        tecman.USE_DB = False
        tecman.MATAFUEGOS_FILE = root / "matafuegos.json"
        tecman.ALERTAS_SYH_FILE = root / "alertas_syh.json"
        tecman.NOTIF_ADMIN_FILE = root / "notif_admin.json"
        tecman.TICKETS_FILE = root / "tickets.json"
        self.own = self._item("mata-014", "014", "2026-07-15", "2025-03-01")
        self.other = self._item("mata-020", "020", "2026-01-10", "2025-01-10")
        tecman.save_matafuegos({"matafuegos": [self.own, self.other]})
        tecman.save_tickets([])
        self.client = tecman.app.test_client()
        self._branch_session("Sucursal 014")

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def _item(item_id, branch, loaded, expires):
        return {
            "id": item_id,
            "sucursal": f"Sucursal {branch}",
            "sucursal_num": branch,
            "tipo": "ABC",
            "cantidad": 1,
            "ubicacion": "Salón",
            "fecha_carga": loaded,
            "fecha_vencimiento": expires,
            "estado_manual": "",
        }

    def _branch_session(self, label, scope=None):
        with self.client.session_transaction() as session:
            session.clear()
            session["suc_user"] = "giuliana-test"
            session["suc_nombre"] = label
            if scope is not None:
                session["suc_general"] = True
                session["suc_scope_nums"] = scope
            session["_csrf_token"] = "csrf-test"

    def _post(self, item_id="mata-014", **overrides):
        data = {
            "_csrf_token": "csrf-test",
            "fecha_carga": "2026-07-24",
            "accion_matafuego": "mantenimiento",
            "observacion_matafuego": "Mantenimiento anual completado",
        }
        data.update(overrides)
        return self.client.post(f"/suc/matafuegos/{item_id}/mantenimiento", data=data)

    def _saved(self):
        return tecman.load_matafuegos()["matafuegos"]

    def test_mantenimiento_valido_calcula_persiste_y_renderiza_proxima_recarga(self):
        response = self._post()
        self.assertEqual(response.status_code, 302)
        saved = next(x for x in self._saved() if x["id"] == "mata-014")
        self.assertEqual(saved["fecha_carga"], "2026-07-24")
        self.assertEqual(saved["fecha_vencimiento_manual"], "2027-07-24")
        self.assertEqual(saved["fecha_vencimiento_original"], "2025-03-01")
        self.assertEqual(tecman._enrich_matafuego(saved)["estado_calc"], "al_dia")

        page = self.client.get("/suc/matafuegos").get_data(as_text=True)
        self.assertIn("Última carga: 2026-07-24", page)
        self.assertIn("2027-07-24", page)
        self.assertNotIn("Matafuegos: revisar vencimientos", page)

    def test_calculo_anual_respeta_bisiesto_y_fin_de_mes(self):
        self.assertEqual(tecman._sumar_un_anio(tecman.datetime.date(2024, 2, 29)), tecman.datetime.date(2025, 2, 28))
        self.assertEqual(tecman._sumar_un_anio(tecman.datetime.date(2026, 1, 31)), tecman.datetime.date(2027, 1, 31))

    def test_vencimiento_proveedor_es_fallback_y_manual_prevalece(self):
        item = self._item("proveedor", "014", "", "2026-01-01")
        item["fecha_vencimiento_proveedor"] = "2027-03-01"
        enriched = tecman._enrich_matafuego(item)
        self.assertEqual(enriched["fecha_control_calc"], "2027-03-01")
        self.assertEqual(enriched["fuente_control"], "fecha_vencimiento_proveedor")
        item["fecha_vencimiento_manual"] = "2028-04-01"
        enriched = tecman._enrich_matafuego(item)
        self.assertEqual(enriched["fecha_control_calc"], "2028-04-01")
        self.assertEqual(enriched["fuente_control"], "fecha_vencimiento_manual")

    def test_catalogo_fuego_cero_no_activa_portal_y_separa_147(self):
        proveedor = next(p for p in tecman.PROVEEDORES if p.get("nombre") == "Fuego Cero")
        self.assertEqual(len(proveedor["sucursales"]), 34)
        self.assertNotIn("147", proveedor["sucursales"])
        self.assertEqual(proveedor["sucursales_pendientes"], {"147": "pendiente_confirmacion"})
        self.assertNotIn("requiere_portal", proveedor)
        self.assertNotIn("036", proveedor["sucursales"])

    def test_fecha_historica_puede_corregirse_y_conserva_auditoria(self):
        first = self._post(
            fecha_carga="2024-02-29",
            observacion_matafuego="Carga histórica informada",
        )
        self.assertEqual(first.status_code, 302)
        saved = next(x for x in self._saved() if x["id"] == "mata-014")
        self.assertEqual(saved["fecha_carga"], "2024-02-29")
        self.assertEqual(saved["fecha_vencimiento_manual"], "2025-02-28")
        self.assertEqual(len(saved["historial_mantenimientos"]), 1)
        self.assertEqual(saved["historial_mantenimientos"][0]["fecha_carga_anterior"], "2026-07-15")
        self.assertEqual(saved["historial_mantenimientos"][0]["fecha_carga"], "2024-02-29")
        self.assertEqual(saved["historial_mantenimientos"][0]["vencimiento_anterior"], "2025-03-01")
        self.assertEqual(saved["historial_mantenimientos"][0]["proxima_recarga"], "2025-02-28")
        self.assertEqual(saved["estado_manual"], "")
        self.assertEqual(tecman.load_tickets(), [])

        reopened = self.client.get("/suc/matafuegos")
        self.assertEqual(reopened.status_code, 200)
        reopened_page = reopened.get_data(as_text=True)
        self.assertIn("Última carga: 2024-02-29", reopened_page)
        self.assertIn("2025-02-28", reopened_page)
        self.assertIn('name="fecha_carga" value="2024-02-29"', reopened_page)

        corrected = self._post(
            fecha_carga="2026-06-30",
            observacion_matafuego="Corrección de fecha según remito",
        )
        self.assertEqual(corrected.status_code, 302)
        saved = next(x for x in self._saved() if x["id"] == "mata-014")
        self.assertEqual(saved["fecha_carga"], "2026-06-30")
        self.assertEqual(saved["fecha_vencimiento_manual"], "2027-06-30")
        self.assertEqual(saved["fecha_vencimiento_original"], "2025-03-01")
        self.assertEqual(len(saved["historial_mantenimientos"]), 2)
        self.assertEqual(saved["historial_mantenimientos"][0]["fecha_carga"], "2024-02-29")
        self.assertEqual(saved["historial_mantenimientos"][1]["fecha_carga_anterior"], "2024-02-29")
        self.assertEqual(saved["historial_mantenimientos"][1]["vencimiento_anterior"], "2025-02-28")
        self.assertEqual(saved["historial_mantenimientos"][1]["fecha_carga"], "2026-06-30")
        self.assertEqual(saved["historial_mantenimientos"][1]["observacion"], "Corrección de fecha según remito")
        self.assertEqual(saved["estado_manual"], "")
        self.assertEqual(tecman.load_tickets(), [])

        page = self.client.get("/suc/matafuegos").get_data(as_text=True)
        self.assertIn("Última carga: 2026-06-30", page)
        self.assertIn("Próxima recarga:", page)
        self.assertIn("2027-06-30", page)
        self.assertIn('name="fecha_carga" value="2026-06-30"', page)
        self.assertIn("Historial de mantenimiento (2)", page)
        self.assertIn("Corrección de fecha según remito", page)

    def test_estado_fecha_y_csrf_invalidos_no_mutan(self):
        cases = [
            {"_csrf_token": ""},
            {"accion_matafuego": "estado-inventado"},
            {"fecha_carga": "24/07/2026"},
            {"fecha_carga": ""},
            {"fecha_carga": "2099-01-01"},
        ]
        for overrides in cases:
            with self.subTest(overrides=overrides):
                before = copy.deepcopy(self._saved())
                response = self._post(**overrides)
                self.assertIn(response.status_code, (302, 400))
                self.assertEqual(self._saved(), before)

    def test_ruta_requiere_rol_de_sucursal(self):
        before = copy.deepcopy(self._saved())
        with self.client.session_transaction() as session:
            session.clear()
            session["user"] = "admin-test"
            session["rol"] = "admin"
            session["_csrf_token"] = "csrf-test"
        response = self._post()
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers["Location"])
        self.assertEqual(self._saved(), before)

    def test_id_ajeno_y_supervisor_fuera_de_scope_no_mutan(self):
        before = copy.deepcopy(self._saved())
        response = self._post(item_id="mata-020")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self._saved(), before)

        self._branch_session("Supervisión", scope=["014"])
        response = self._post(item_id="mata-020")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self._saved(), before)

    def test_formulario_incluye_csrf_y_no_pide_proxima_recarga_en_detalle(self):
        page = self.client.get("/suc/matafuegos").get_data(as_text=True)
        self.assertIn('name="_csrf_token" value="csrf-test"', page)
        self.assertIn('name="fecha_carga"', page)
        self.assertNotIn('placeholder="Próxima recarga', page)

    def test_persistencia_db_usa_el_mismo_payload_calculado(self):
        with patch.object(tecman, "MatafuegoDB", object(), create=True), \
             patch.object(tecman, "_db_list", return_value=[copy.deepcopy(self.own), copy.deepcopy(self.other)]), \
             patch.object(tecman, "_db_replace") as replace, \
             patch.object(tecman, "_atomic_write") as atomic_write, \
             patch.object(tecman, "sync_alertas_syh"):
            tecman.USE_DB = True
            try:
                response = self._post()
            finally:
                tecman.USE_DB = False
        self.assertEqual(response.status_code, 302)
        persisted = replace.call_args.args[1]
        updated = next(x for x in persisted if x["id"] == "mata-014")
        self.assertEqual(updated["fecha_carga"], "2026-07-24")
        self.assertEqual(updated["fecha_vencimiento_manual"], "2027-07-24")
        self.assertEqual(updated["historial_mantenimientos"][0]["fecha_carga"], "2026-07-24")
        self.assertEqual(updated["historial_mantenimientos"][0]["proxima_recarga"], "2027-07-24")
        atomic_write.assert_called()


if __name__ == "__main__":
    unittest.main()
