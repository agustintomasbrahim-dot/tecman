import ast
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_script(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


generators = load_script("generator_migration", "scripts/migrate_generadores_20260928.py")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class InventoryIntegrationTests(unittest.TestCase):
    def test_provider_scopes_are_exact_and_disjoint(self):
        dip = json.loads((ROOT / "reportes/diprogom_import_preview_2026-09-24.json").read_text(encoding="utf-8"))
        fuego = json.loads((ROOT / "reportes/fuego_cero_import_preview_2026-09-28.json").read_text(encoding="utf-8"))
        dip_branches = set(dip["active_branch_numbers"])
        fuego_branches = set(fuego["confirmed_branch_numbers"])
        self.assertEqual(len(dip_branches), 25)
        self.assertEqual(len(fuego_branches), 35)
        self.assertEqual(dip_branches & fuego_branches, set())

    def test_generator_migration_is_explicit_idempotent_and_byte_reversible(self):
        source = ROOT / "reportes/generadores_captura_2026-09-28.json"
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            original = base / "input.json"
            before = {"grupos_electrogenos": [{
                "id": "ge-20260923-077", "sucursal": "Sucursal 077", "sucursal_num": "077",
                "marca": "dato anterior", "estado_validacion": "con_diferencias",
                "novedades": [{"id": "operativa"}], "historial": [{"accion": "anterior"}],
                "fuente_importacion": "inventario_grupos_2026-09-23",
            }]}
            write_json(original, before)
            plan_path = base / "plan.json"; output = base / "output.json"
            journal = base / "journal.json"; restored = base / "restored.json"
            plan = generators.make_plan(original, sha(original), source, sha(source))
            self.assertEqual(plan["summary"]["source_rows"], 21)
            self.assertEqual(plan["summary"]["operations"], 21)
            self.assertFalse(plan["safety"]["auto_start"])
            write_json(plan_path, plan)
            generators.apply_plan(original, sha(original), source, sha(source), plan_path, sha(plan_path), output, journal)
            applied = json.loads(output.read_text(encoding="utf-8"))
            row = next(item for item in applied["grupos_electrogenos"] if item["sucursal_num"] == "077")
            self.assertEqual(row["id"], "ge-20260923-077")
            self.assertEqual(row["marca"], "Vanguard")
            self.assertEqual(row["estado_validacion"], "con_diferencias")
            self.assertEqual(row["novedades"], [{"id": "operativa"}])
            repeated = generators.make_plan(output, sha(output), source, sha(source))
            self.assertEqual(repeated["summary"]["operations"], 0)
            generators.rollback(output, sha(output), journal, restored)
            self.assertEqual(restored.read_bytes(), original.read_bytes())

    def test_application_startup_does_not_call_generator_migration(self):
        tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))
        startup_calls = []

        def visit(node):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
                return
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                startup_calls.append(node.func.id)
            for child in ast.iter_child_nodes(node):
                visit(child)

        for node in tree.body:
            visit(node)
        self.assertNotIn("_ensure_grupos_electrogenos_inventario_2026_09", startup_calls)


if __name__ == "__main__":
    unittest.main()
