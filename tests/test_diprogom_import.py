import hashlib
import importlib.util
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
try:
    import xlrd  # noqa: F401
except ImportError:
    fake_xlrd = types.ModuleType("xlrd")
    fake_xlrd.XLRDError = ValueError
    sys.modules["xlrd"] = fake_xlrd

spec = importlib.util.spec_from_file_location("import_diprogom", ROOT / "scripts" / "import_diprogom.py")
dip = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dip)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


class FakeSheet:
    def __init__(self, rows, green_rows=None):
        self._rows = rows
        self._green_rows = set(green_rows or [])
        self.nrows = len(rows)
        self.ncols = len(rows[0])

    def row_values(self, index):
        return list(self._rows[index])

    def cell(self, row_index, column_index):
        return types.SimpleNamespace(xf_index=1 if row_index in self._green_rows else 0)


class FakeWorkbook:
    def __init__(self):
        self.colour_map = {dip.GREEN_FILL_INDEX: dip.GREEN_FILL_RGB, 47: (255, 204, 153)}
        normal = types.SimpleNamespace(fill_pattern=1, pattern_colour_index=47)
        green = types.SimpleNamespace(fill_pattern=1, pattern_colour_index=dip.GREEN_FILL_INDEX)
        self.xf_list = [types.SimpleNamespace(background=normal), types.SimpleNamespace(background=green)]


def synthetic_sheet():
    rows = [[dip.TITLE] + [""] * 9, [""] * 10, list(dip.HEADERS)]
    green_rows = []
    identifier = 100000

    def add(branch, count, *, fallback=False, pending=False, inactive_green=False):
        nonlocal identifier
        for branch_index in range(count):
            identifier += 1
            if pending:
                name, address = dip.PENDING_LABEL, dip.PENDING_ADDRESS
            elif fallback:
                name, address = "", f"CONSTITUCION 524 SUC {int(branch)} MOOV"
            else:
                name, address = f"LOCAL {int(branch)} - DEXTER", "DOMICILIO"
            rows.append(["DABRA S.A.", name, address, "06-27.", float(identifier), 1.0, 2.0, 2020.0, "POLVO ABC", 5.0])
            if inactive_green and branch_index == 0:
                green_rows.append(len(rows) - 1)

    active = ["036", "043", "053", "077", "171", "176", "177", "184", "185", "187", "188", "190", "194", "198", "200", "202", "204", "208", "209", "216", "219", "221", "222", "232"]
    for branch in active:
        add(branch, 15 if branch != "036" else 4)  # 349 rows among these 24 branches
    add("167", 19, inactive_green=True)
    add("183", 29, inactive_green=True)
    add("213", 27, inactive_green=True)
    add("214", 9, fallback=True)
    add("051", 13)
    add("156", 23)
    add(None, 14, pending=True)
    return FakeSheet(rows, green_rows)


def source(rows):
    branches = sorted({row["sucursal_num"] for row in rows})
    return {
        "schema": "tecman.diprogom-source/v1",
        "xls": "/tmp/source.xls",
        "xls_sha256": dip.EXPECTED_XLS_SHA256,
        "rows": rows,
        "active_branch_numbers": branches,
        "inactive_green_branch_numbers": [],
        "summary": {
            "rows": len(rows), "unique_extinguisher_ids": len(rows), "numbered_rows": len(rows),
            "numbered_branches": len(branches), "active_rows": len(rows), "active_branches": len(branches),
            "inactive_green_rows": 0, "inactive_green_branches": {}, "green_fill_index": 49,
            "green_fill_rgb": [51, 204, 204], "green_marker_rows": [],
            "conflict_rows": 0, "conflict_branches": {"051": 13, "156": 23}, "pending_rows": 14,
            "pending_label": dip.PENDING_LABEL, "fallback_214_rows": 9, "count_validation": "ok",
        },
    }


def row(number, identifier, branch="001", kind="ABC", capacity="5 KG", due="2027-06-01"):
    return {
        "row": number, "sucursal_num": branch, "branch_source": "nombre_suc", "pending": False,
        "nro_extintor": identifier, "fecha_vencimiento_proveedor": due, "tipo": kind, "capacidad": capacity,
        "green_marker": False, "inactive_green": False,
    }


class DiprogomImportTests(unittest.TestCase):
    def test_synthetic_exact_headers_counts_dates_normalization_and_fallback(self):
        parsed = dip.parse_sheet(synthetic_sheet(), Path("synthetic.xls"), "f" * 64, FakeWorkbook())
        self.assertEqual(parsed["summary"]["rows"], 483)
        self.assertEqual(parsed["summary"]["numbered_rows"], 469)
        self.assertEqual(parsed["summary"]["numbered_branches"], 30)
        self.assertEqual(parsed["summary"]["active_rows"], 358)
        self.assertEqual(parsed["summary"]["active_branches"], 25)
        self.assertEqual(parsed["summary"]["inactive_green_rows"], 75)
        self.assertEqual(parsed["summary"]["inactive_green_branches"], {"167": 19, "183": 29, "213": 27})
        self.assertEqual(parsed["summary"]["green_fill_index"], 49)
        self.assertEqual(parsed["summary"]["green_fill_rgb"], [51, 204, 204])
        self.assertEqual(len(parsed["summary"]["green_marker_rows"]), 3)
        self.assertEqual(parsed["summary"]["conflict_branches"], {"051": 13, "156": 23})
        self.assertEqual(parsed["summary"]["pending_rows"], 14)
        self.assertEqual(parsed["summary"]["fallback_214_rows"], 9)
        fallback = [item for item in parsed["rows"] if item["branch_source"] == "domicilio_fallback"]
        self.assertEqual({item["sucursal_num"] for item in fallback}, {"214"})
        self.assertEqual(parsed["rows"][0]["fecha_vencimiento_proveedor"], "2027-06-01")
        self.assertEqual(parsed["rows"][0]["tipo"], "ABC")
        self.assertEqual(parsed["rows"][0]["capacidad"], "5 KG")
        for branch, count in dip.INACTIVE_GREEN_BRANCHES.items():
            branch_rows = [item for item in parsed["rows"] if item["sucursal_num"] == branch]
            self.assertEqual(len(branch_rows), count)
            self.assertTrue(all(item["inactive_green"] for item in branch_rows))
            self.assertEqual(sum(item["green_marker"] for item in branch_rows), 1)

    def test_exact_headers_duplicate_ids_and_strict_dates_are_rejected(self):
        sheet = synthetic_sheet()
        sheet._rows[2][0] = "CLIENTE"
        with self.assertRaisesRegex(ValueError, "encabezados"):
            dip.parse_sheet(sheet, Path("bad.xls"), "f" * 64, FakeWorkbook())
        self.assertEqual(dip.monthly_date("02-27."), "2027-02-01")
        for invalid in ("2-27.", "02/27", "02-2027.", "13-27."):
            with self.assertRaises(ValueError):
                dip.monthly_date(invalid)

    def test_primary_secondary_add_conflict_safe_delete_idempotence_and_rollback(self):
        rows = [row(4, "A"), row(5, "MISSING"), row(6, "NEW"), row(7, "BAD")]
        parsed = source(rows)
        before = {"matafuegos": [
            {"id": "manual", "sucursal_num": "001", "sucursal": "Sucursal 001", "tipo": "ABC", "capacidad": "5 KG", "nro_extintor": "A", "fecha_vencimiento": "2025-01-01", "fecha_vencimiento_manual": "2030-04-01", "historial_mantenimientos": [{"accion": "manual"}]},
            {"id": "secondary", "sucursal_num": "001", "sucursal": "Sucursal 001", "tipo": "ABC", "capacidad": "5 KG", "nro_extintor": "OLD", "fecha_vencimiento": "2025-01-01"},
            {"id": "bad", "sucursal_num": "002", "sucursal": "Sucursal 002", "tipo": "ABC", "capacidad": "5 KG", "nro_extintor": "BAD", "fecha_vencimiento": "2025-01-01"},
            {"id": "extra", "sucursal_num": "001", "sucursal": "Sucursal 001", "tipo": "ABC", "capacidad": "10 KG", "nro_extintor": "EXTRA", "proveedor_nombre": "Diprogom", "proveedor_origen": "diprogom_xls"},
        ]}
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            original, xls = base / "matafuegos.json", base / "source.xls"
            plan_path, output = base / "plan.json", base / "out.json"
            journal, restored = base / "journal.json", base / "restored.json"
            write_json(original, before)
            xls.write_bytes(b"fixture")
            with mock.patch.object(dip, "parse_xls", return_value=parsed):
                plan = dip.make_plan(original, xls, sha(original))
            self.assertEqual(plan["summary"], {"adds": 1, "updates": 2, "safe_deletes": 1, "conflicts": 1, "operations": 4, "input_total": 4, "final_total": 4, "automatic_scope_branches": 1, "automatic_scope_equipment": 4})
            self.assertEqual(plan["match_summary"], {"alta": 1, "nro_extintor": 1, "sucursal_tipo_capacidad": 1})
            write_json(plan_path, plan)
            dip.apply_plan(original, sha(original), plan_path, output, journal)
            after = json.loads(output.read_text(encoding="utf-8"))
            manual = next(item for item in after["matafuegos"] if item["id"] == "manual")
            self.assertEqual(manual["fecha_vencimiento_manual"], "2030-04-01")
            self.assertEqual(manual["fecha_vencimiento"], "2025-01-01")
            self.assertEqual(manual["fecha_vencimiento_proveedor"], "2027-06-01")
            self.assertEqual(manual["historial_mantenimientos"], [{"accion": "manual"}])
            secondary = next(item for item in after["matafuegos"] if item["id"] == "secondary")
            self.assertEqual(secondary["nro_extintor"], "OLD")
            self.assertEqual(secondary["proveedor_nro_extintor"], "MISSING")
            with mock.patch.object(dip, "parse_xls", return_value=parsed):
                repeated = dip.make_plan(output, xls, sha(output))
            self.assertEqual(repeated["summary"]["operations"], 0)
            self.assertEqual(repeated["summary"]["conflicts"], 1)
            dip.rollback(output, sha(output), journal, restored)
            self.assertEqual(json.loads(restored.read_text(encoding="utf-8")), before)
            self.assertEqual(sha(restored), sha(original))

    def test_sha_in_place_and_activity_guards(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            original, plan_path, journal = base / "matafuegos.json", base / "plan.json", base / "journal.json"
            write_json(original, {"matafuegos": []})
            with self.assertRaisesRegex(ValueError, "precondición SHA"):
                dip.load_inventory(original, "0" * 64)
            with self.assertRaisesRegex(ValueError, "rutas deben ser distintas"):
                dip.apply_plan(original, sha(original), plan_path, original, journal)
        self.assertTrue(dip.has_activity({"historial": [{"x": 1}]}))
        self.assertFalse(dip.supplier_owned_inactive({"proveedor_nombre": "Diprogom", "proveedor_origen": "diprogom_xls", "estado_manual": "observado"}))

    def test_green_branches_never_mutate_even_when_inventory_is_diprogom_owned(self):
        inactive = row(4, "GREEN", branch="183")
        inactive["inactive_green"] = True
        parsed = source([row(5, "ACTIVE")])
        parsed["rows"].append(inactive)
        parsed["inactive_green_branch_numbers"] = ["183"]
        before = {"matafuegos": [
            {"id": "green", "sucursal_num": "183", "sucursal": "Sucursal 183", "tipo": "ABC", "capacidad": "5 KG", "nro_extintor": "GREEN", "proveedor_nombre": "Diprogom", "proveedor_origen": "diprogom_xls"},
        ]}
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            original, xls = base / "matafuegos.json", base / "source.xls"
            write_json(original, before)
            xls.write_bytes(b"fixture")
            with mock.patch.object(dip, "parse_xls", return_value=parsed):
                plan = dip.make_plan(original, xls, sha(original))
        self.assertFalse(any(op.get("item_id") == "green" for op in plan["operations"]))
        self.assertEqual(plan["inactive_green"], {"branch_counts": {"183": 1}, "rows": 1, "status": "historico_inactivo_no_asignar_diprogom"})
        self.assertEqual(plan["safety"]["inactive_green_mutations"], 0)

    def test_parse_xls_requires_formatting_info(self):
        workbook = mock.Mock()
        workbook.sheet_names.return_value = [dip.SHEET_NAME]
        workbook.sheet_by_name.return_value = synthetic_sheet()
        workbook.colour_map = FakeWorkbook().colour_map
        workbook.xf_list = FakeWorkbook().xf_list
        with mock.patch.object(dip, "sha256_file", return_value=dip.EXPECTED_XLS_SHA256), mock.patch.object(dip.xlrd, "open_workbook", return_value=workbook) as opened, mock.patch.object(dip.xlrd, "__version__", dip.XLRD_VERSION, create=True):
            dip.parse_xls(Path("source.xls"))
        opened.assert_called_once_with("source.xls", on_demand=True, formatting_info=True)

    def test_catalog_has_active_inactive_conflicts_and_pending_without_new_credentials(self):
        app = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn('"diprogom": {"password": _PROVEEDOR_PWD, "nombre": "Diprogom", "tipo_cuenta": "matafuegos", "proveedores": ["Diprogom"]}', app)
        marker = next(line for line in app.splitlines() if '{"nombre": "Diprogom"' in line)
        self.assertIn('"sucursales_conflicto": {"051": 13, "156": 23}', marker)
        self.assertIn('"sucursales_pendientes": {"MORZAT": 14}', marker)
        self.assertEqual(marker.split('"sucursales": [', 1)[1].split(']', 1)[0].count('"') // 2, 25)
        self.assertIn('"sucursales_inactivas_verdes": {"167": 19, "183": 29, "213": 27}', marker)


if __name__ == "__main__":
    unittest.main()
