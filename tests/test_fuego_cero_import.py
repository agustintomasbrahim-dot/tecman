import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import import_fuego_cero as fuego  # noqa: E402


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def write_xlsx(path, rows):
    wb = Workbook(); ws = wb.active; ws.title = "Hoja1"
    ws.append(list(fuego.HEADERS))
    for row in rows: ws.append(row)
    wb.save(path)


def source_row(local, due="03/2027", counts=(1, 0, 0, 0, 0, 0), name="LOCAL"):
    return [local, "DEXTER", name, "Dirección", due, *counts, "10 a 20", "Localidad", "Buenos Aires", None, None]


class FuegoCeroImportTests(unittest.TestCase):
    def test_synthetic_exact_totals_headers_dates_and_missing_local(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "fuego.xlsx"
            branches = list(range(1, 35)) + [147]
            rows = [source_row(n, counts=(415 if n == 1 else 0, 0, 0, 0, 0, 0)) for n in branches]
            rows += [source_row(None, counts=(0, 0, 0, 1, 0, 0), name="DON TORCUATO"),
                     source_row(None, due="09/2027", counts=(81, 0, 1, 4, 0, 7), name="GARIN")]
            write_xlsx(path, rows)
            parsed = fuego.parse_xlsx(path)
        self.assertEqual(parsed["summary"]["numbered_branches_observed"], 35)
        self.assertEqual(parsed["summary"]["confirmed_branches"], 34)
        self.assertEqual(parsed["summary"]["total_equipment"], 509)
        self.assertEqual(parsed["summary"]["unnumbered_equipment"], 94)
        self.assertEqual(parsed["summary"]["count_validation"], "ok")
        self.assertEqual(parsed["branches"]["001"]["fecha_vencimiento_proveedor"], "2027-03-01")
        self.assertEqual({x["name"].split()[-1] for x in parsed["unnumbered"]}, {"TORCUATO", "GARIN"})

    def test_exact_headers_are_required(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "bad.xlsx"
            wb = Workbook(); ws = wb.active; ws.title = "Hoja1"
            headers = list(fuego.HEADERS); headers[5] = "ABC 5"; ws.append(headers); wb.save(path)
            with self.assertRaisesRegex(ValueError, "encabezados"):
                fuego.parse_xlsx(path)

    def test_pending_147_excluded_manual_preserved_conflict_idempotence_and_rollback(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d); xlsx = base / "fuego.xlsx"; original = base / "matafuegos.json"
            plan_path = base / "plan.json"; output = base / "out.json"; journal = base / "journal.json"; restored = base / "restored.json"
            rows = [source_row(11, counts=(2, 0, 0, 0, 0, 0)), source_row(147, counts=(3, 0, 0, 0, 0, 0)),
                    source_row(None, counts=(0, 0, 0, 1, 0, 0), name="DON TORCUATO"),
                    source_row(None, counts=(0, 0, 0, 0, 0, 1), name="GARIN")]
            write_xlsx(xlsx, rows)
            before = {"matafuegos": [
                {"id": "manual", "sucursal_num": "011", "sucursal": "Sucursal 011", "tipo": "ABC", "capacidad": "5 KG", "cantidad": 1,
                 "fecha_vencimiento": "2025-01-01", "fecha_vencimiento_manual": "2030-04-01", "historial_mantenimientos": [{"accion": "mantenimiento"}], "actualizado_por_sucursal": "011"},
                {"id": "extra", "sucursal_num": "011", "sucursal": "Sucursal 011", "tipo": "ABC", "capacidad": "5 KG", "cantidad": 1,
                 "fecha_vencimiento": "2025-01-01", "estado_manual": "rechazado"},
                {"id": "third", "sucursal_num": "011", "sucursal": "Sucursal 011", "tipo": "ABC", "capacidad": "5 KG", "cantidad": 1,
                 "fecha_vencimiento": "2025-01-01", "historial": [{"x": 1}]},
                {"id": "p147", "sucursal_num": "147", "sucursal": "Sucursal 147", "tipo": "ABC", "capacidad": "5 KG", "cantidad": 1},
            ]}
            write_json(original, before)
            plan = fuego.make_plan(original, xlsx, sha(original))
            write_json(plan_path, plan)
            self.assertEqual(plan["pending"], {"147": "pendiente_confirmacion"})
            self.assertFalse(any((op.get("before") or op.get("after") or {}).get("sucursal_num") == "147" for op in plan["operations"]))
            self.assertEqual(plan["summary"]["conflicts"], 1)
            fuego.apply_plan(original, sha(original), plan_path, output, journal)
            after = json.loads(output.read_text())
            manual = next(x for x in after["matafuegos"] if x["id"] == "manual")
            self.assertEqual(manual["fecha_vencimiento_manual"], "2030-04-01")
            self.assertEqual(manual["fecha_vencimiento"], "2025-01-01")
            self.assertEqual(manual["fecha_vencimiento_proveedor"], "2027-03-01")
            self.assertEqual(manual["historial_mantenimientos"], [{"accion": "mantenimiento"}])
            repeated = fuego.make_plan(output, xlsx, sha(output))
            self.assertEqual(repeated["summary"]["operations"], 0)
            self.assertEqual(repeated["summary"]["conflicts"], 1)
            fuego.rollback(output, sha(output), journal, restored)
            self.assertEqual(json.loads(restored.read_text()), before)

    def test_sha_is_mandatory_in_place_is_refused_and_add_id_is_deterministic(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d); xlsx = base / "f.xlsx"; original = base / "matafuegos.json"
            write_xlsx(xlsx, [source_row(11, counts=(1, 0, 0, 0, 0, 0)), source_row(147, counts=(0, 0, 0, 0, 0, 0)),
                              source_row(None, counts=(0, 0, 0, 0, 0, 0), name="DON TORCUATO"), source_row(None, counts=(0, 0, 0, 0, 0, 0), name="GARIN")])
            write_json(original, {"matafuegos": []})
            with self.assertRaisesRegex(ValueError, "precondición SHA"):
                fuego.make_plan(original, xlsx, "0" * 64)
            first = fuego.make_plan(original, xlsx, sha(original))
            second = fuego.make_plan(original, xlsx, sha(original))
            self.assertEqual(first["summary"]["adds"], 1)
            self.assertEqual(first["operations"][0]["item_id"], second["operations"][0]["item_id"])
            plan_path = base / "plan.json"; journal = base / "journal.json"; write_json(plan_path, first)
            with self.assertRaisesRegex(ValueError, "rutas deben ser distintas"):
                fuego.apply_plan(original, sha(original), plan_path, original, journal)

    def test_safe_supplier_extra_is_deleted_and_restored(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d); xlsx = base / "f.xlsx"; original = base / "matafuegos.json"
            plan_path = base / "plan.json"; output = base / "out.json"; journal = base / "journal.json"; restored = base / "restored.json"
            write_xlsx(xlsx, [source_row(11, counts=(1, 0, 0, 0, 0, 0)), source_row(147, counts=(0, 0, 0, 0, 0, 0)),
                              source_row(None, counts=(0, 0, 0, 0, 0, 0), name="DON TORCUATO"), source_row(None, counts=(0, 0, 0, 0, 0, 0), name="GARIN")])
            before = {"matafuegos": [
                {"id": "a", "sucursal_num": "011", "sucursal": "Sucursal 011", "tipo": "ABC", "capacidad": "5 KG", "proveedor_nombre": "Fuego Cero", "proveedor_origen": "fuego_cero_xlsx"},
                {"id": "b", "sucursal_num": "011", "sucursal": "Sucursal 011", "tipo": "ABC", "capacidad": "5 KG", "proveedor_nombre": "Fuego Cero", "proveedor_origen": "fuego_cero_xlsx"},
            ]}
            write_json(original, before); plan = fuego.make_plan(original, xlsx, sha(original)); write_json(plan_path, plan)
            self.assertEqual(plan["summary"]["safe_deletes"], 1)
            fuego.apply_plan(original, sha(original), plan_path, output, journal)
            fuego.rollback(output, sha(output), journal, restored)
            self.assertEqual(json.loads(restored.read_text()), before)


if __name__ == "__main__": unittest.main()
