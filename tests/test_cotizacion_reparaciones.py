import copy
import hashlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openpyxl import load_workbook


_TEST_ROOT = tempfile.TemporaryDirectory()
os.environ["TECMAN_DATA_DIR"] = str(Path(_TEST_ROOT.name) / "data")
os.environ["TECMAN_UPLOADS_DIR"] = str(Path(_TEST_ROOT.name) / "uploads")
os.environ.pop("DATABASE_URL", None)

import app as tecman  # noqa: E402


class CotizacionReparacionesTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        tecman.app.config.update(TESTING=True, SECRET_KEY="test-only", SERVER_NAME="localhost")
        tecman.USE_DB = False
        tecman.TICKETS_FILE = root / "tickets.json"
        tecman.NOTIF_ADMIN_FILE = root / "notif_admin.json"
        tecman.UPLOADS_DIR = root / "uploads"
        tecman.UPLOADS_DIR.mkdir(parents=True)
        tecman.save_notif_admin({"notificaciones": [{"id": "keep", "leida": False}]})
        tecman.save_tickets(self._tickets())
        self.client = tecman.app.test_client()
        self._admin_session()

    def tearDown(self):
        tecman.USE_DB = False
        self.temp.cleanup()

    @staticmethod
    def _tickets():
        base = {
            "categoria": "Reparaciones",
            "subcategoria": "General",
            "descripcion": "Reparar persiana",
            "prioridad": 2,
            "estado": "Nuevo",
            "creado": "2026-09-01T09:30:00",
            "actualizado": "2026-09-02T10:00:00",
            "observaciones": "Coordinar antes de visitar",
            "fotos": [],
        }
        rows = [
            dict(base, id=101, sucursal="Sucursal 120", asignado="Julio Fuga (JRF)", fotos=["foto 1.jpg"], notas=[{"autor": "Admin", "fecha": "2026-09-02T10:00:00", "texto": "Revisar motor"}]),
            dict(base, id=102, sucursal="Sucursal 120", asignado="Carolina", proveedor_nombre="JRF", zona_afectada="Salón"),
            dict(base, id=103, sucursal="Sucursal 126", asignado="Carolina", asignado_proveedor="fuga", descripcion="=2+2 no debe ser fórmula", presupuestos=[{"archivo": "presupuesto.pdf"}]),
            dict(base, id=104, sucursal="Sucursal 126", asignado="Ismael Allende (JRF)"),
            dict(base, id=105, sucursal="Sucursal 139", asignado="Julio Fuga", estado="Resuelto"),
            dict(base, id=106, sucursal="Sucursal 139", proveedor_nombre="Ismael Allende", estado="Cerrado"),
            dict(base, id=107, sucursal="Sucursal 145", asignado_proveedor="ismael", estado="Rechazado"),
            dict(base, id=201, sucursal="Sucursal 120", asignado="Otro proveedor"),
            dict(base, id=202, sucursal="Sucursal 120", proveedor_nombre="JRF Servicios Integrales"),
            dict(base, id=203, sucursal="Sucursal 120", asignado="No Julio Fuga"),
        ]
        return rows

    def _admin_session(self, csrf="csrf-test"):
        with self.client.session_transaction() as session:
            session.clear()
            session["user"] = "admin-test"
            session["rol"] = "admin"
            session["nombre"] = "Agustín"
            session["_csrf_token"] = csrf

    @staticmethod
    def _digest(path):
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()

    def _post(self, ids, **extra):
        data = {
            "_csrf_token": "csrf-test",
            "include_finalizados": "0",
            "proveedor_destino": "Nuevo Proveedor SRL",
            "ticket_ids": [str(value) for value in ids],
        }
        data.update(extra)
        return self.client.post("/admin/cotizacion-reparaciones", data=data)

    def test_clasificacion_exacta_aliases_campos_y_estados_finales(self):
        tickets = self._tickets()
        open_ids = [ticket["id"] for ticket in tecman._tickets_cotizables_julio_fuga(tickets)]
        all_ids = [ticket["id"] for ticket in tecman._tickets_cotizables_julio_fuga(tickets, include_finalizados=True)]

        self.assertEqual(open_ids, [101, 102, 103, 104])
        self.assertEqual(all_ids, [101, 102, 103, 104, 105, 106, 107])
        self.assertFalse(tecman._ticket_es_de_julio_fuga(tickets[7]))
        self.assertFalse(tecman._ticket_es_de_julio_fuga(tickets[8]))
        self.assertFalse(tecman._ticket_es_de_julio_fuga(tickets[9]))
        self.assertEqual(tecman.TICKET_FINAL_STATES, {"Rechazado", "Resuelto", "Cerrado"})

    def test_render_agrupa_por_sucursal_abiertos_y_controles_de_seleccion(self):
        response = self.client.get("/admin/cotizacion-reparaciones")
        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)

        self.assertIn("Cotización de reparaciones", page)
        self.assertIn("4 tickets", page)
        self.assertEqual(page.count('<section class="card quote-branch" data-branch-group>'), 2)
        self.assertEqual(page.count('type="checkbox" data-select-branch'), 2)
        for ticket_id in (101, 102, 103, 104):
            self.assertIn(f'value="{ticket_id}"', page)
        for ticket_id in (105, 106, 107, 201, 202, 203):
            self.assertNotIn(f'value="{ticket_id}"', page)
        self.assertIn('name="_csrf_token" value="csrf-test"', page)
        self.assertIn('maxlength="120"', page)

        with_final = self.client.get("/admin/cotizacion-reparaciones?include_finalizados=1").get_data(as_text=True)
        for ticket_id in (105, 106, 107):
            self.assertIn(f'value="{ticket_id}"', with_final)

    def test_xlsx_resumen_hojas_columnas_filas_proveedor_y_enlaces(self):
        before_tickets = self._digest(tecman.TICKETS_FILE)
        before_notices = self._digest(tecman.NOTIF_ADMIN_FILE)
        response = self._post([104, 101, 103])

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        self.assertIn("cotizacion_reparaciones_", response.headers["Content-Disposition"])
        workbook = load_workbook(io.BytesIO(response.data), data_only=False)
        self.assertEqual(workbook.sheetnames, ["Resumen", "Sucursal 120", "Sucursal 126"])

        summary = workbook["Resumen"]
        self.assertEqual(summary["A1"].value, "Cotización de reparaciones")
        self.assertEqual(summary["B2"].value, "Nuevo Proveedor SRL")
        self.assertEqual(summary["B4"].value, 3)
        self.assertEqual(summary["A7"].value, "Sucursal 120")
        self.assertEqual(summary["B7"].value, 1)
        self.assertEqual(summary["A8"].value, "Sucursal 126")
        self.assertEqual(summary["B8"].value, 2)

        sheet_120 = workbook["Sucursal 120"]
        headers = [cell.value for cell in sheet_120[5]]
        self.assertEqual(headers[:12], [
            "Sucursal", "Ticket", "Categoría", "Subcategoría", "Descripción / problema",
            "Zona / ubicación", "Prioridad", "Estado", "Fecha", "Antigüedad (días)",
            "Observaciones relevantes", "Ver ticket",
        ])
        self.assertIn("Adjunto 1", headers)
        self.assertEqual(sheet_120.max_row, 6)
        self.assertEqual(sheet_120["B6"].value, "101")
        self.assertEqual(sheet_120["B2"].value, "Nuevo Proveedor SRL")
        self.assertEqual(sheet_120["L6"].hyperlink.target, "http://localhost/admin/ticket/101")
        self.assertEqual(sheet_120["M6"].hyperlink.target, "http://localhost/static/uploads/foto%201.jpg")
        self.assertIn("Revisar motor", sheet_120["K6"].value)

        sheet_126 = workbook["Sucursal 126"]
        self.assertEqual([sheet_126[f"B{row}"].value for row in (6, 7)], ["103", "104"])
        self.assertEqual(sheet_126["E6"].value, "'=2+2 no debe ser fórmula")
        self.assertEqual(sheet_126["M6"].hyperlink.target, "http://localhost/static/uploads/presupuesto.pdf")
        workbook.close()

        self.assertEqual(self._digest(tecman.TICKETS_FILE), before_tickets)
        self.assertEqual(self._digest(tecman.NOTIF_ADMIN_FILE), before_notices)
        self.assertEqual(list(tecman.UPLOADS_DIR.iterdir()), [])

    def test_ids_manipulados_vacio_csrf_y_sesion_rechazan_sin_mutar(self):
        cases = [
            ([], {}, 400),
            ([201], {}, 400),
            ([105], {}, 400),
            ([101, 101], {}, 400),
            ([101], {"_csrf_token": "incorrecto"}, 400),
            ([101], {"proveedor_destino": "x" * 121}, 400),
        ]
        for ids, extra, expected in cases:
            with self.subTest(ids=ids, extra=extra):
                before_tickets = self._digest(tecman.TICKETS_FILE)
                before_notices = self._digest(tecman.NOTIF_ADMIN_FILE)
                response = self._post(ids, **extra)
                self.assertEqual(response.status_code, expected)
                self.assertEqual(self._digest(tecman.TICKETS_FILE), before_tickets)
                self.assertEqual(self._digest(tecman.NOTIF_ADMIN_FILE), before_notices)

        with self.client.session_transaction() as session:
            session.clear()
        no_session = self.client.get("/admin/cotizacion-reparaciones")
        self.assertEqual(no_session.status_code, 302)
        self.assertIn("/admin/login", no_session.headers["Location"])

        self._admin_session()
        valid_final = self._post([105], include_finalizados="1")
        self.assertEqual(valid_final.status_code, 200)

    def test_lectura_db_usa_payload_sin_persistir(self):
        tickets = copy.deepcopy(self._tickets())
        ticket_model = object()
        with patch.object(tecman, "TicketDB", ticket_model, create=True), \
             patch.object(tecman, "_db_list", return_value=copy.deepcopy(tickets)) as db_list, \
             patch.object(tecman, "_db_replace") as db_replace, \
             patch.object(tecman, "USE_DB", True):
            response = self.client.get("/admin/cotizacion-reparaciones")

        self.assertEqual(response.status_code, 200)
        db_list.assert_called_once_with(ticket_model)
        db_replace.assert_not_called()
        self.assertEqual(tickets, self._tickets())

    def test_nombres_de_hoja_validos_y_unicos(self):
        tickets = [
            dict(self._tickets()[0], id=301, sucursal="Sucursal [Norte]/Nombre extremadamente largo 1234567890"),
            dict(self._tickets()[1], id=302, sucursal="Sucursal :Norte?/Nombre extremadamente largo 1234567890"),
        ]
        with tecman.app.test_request_context("/", base_url="http://localhost"):
            workbook = tecman._build_quote_workbook(tickets, "", generated_at=tecman.datetime.datetime(2026, 9, 18, 10, 0))
        self.assertEqual(workbook.sheetnames[0], "Resumen")
        self.assertEqual(len(workbook.sheetnames), len(set(name.casefold() for name in workbook.sheetnames)))
        for name in workbook.sheetnames:
            self.assertLessEqual(len(name), 31)
            self.assertFalse(any(char in name for char in "[]:*?/\\"))
        workbook.close()


if __name__ == "__main__":
    unittest.main()
