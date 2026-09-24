import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import prepare_invgate_tickets_from_excel as prepare  # noqa: E402
import reconcile_invgate_migration as reconcile  # noqa: E402


def write_workbook(path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Proveedor Uno"
    ws.append([
        "SUCURSAL", "Estado", "Prioridad", "Fecha de solicitud",
        "Fecha de realización", "Demora de ticket", "Provincia",
        "Nro de Ticket", "Solicitud", "Materiales", "Ubicación de materiales",
    ])
    ws.append([12, "No comenzado", 4, "20/08/2026", "se pidió repuesto", "2 días", "AMBA", 12345, "Reparar puerta", "bisagra", "depósito"])
    ws.append([13, "Nombre sucursal", "Marca", None, None, None, None, None, None, None, None])
    ws.append(["Proveedor: Uno", None, None, "contacto operativo", None, None, None, None, None, None, None])
    wb.save(path)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def input_tickets() -> list[dict]:
    return [
        {"id": 100001, "sucursal": "Sucursal 012", "sucursal_num": "012", "estado": "Resuelto",
         "asignado": "Operador actual", "descripcion": "20/08/2026", "origen": "InvGate", "invgate_ticket_id": "",
         "invgate_hoja": "Proveedor Uno", "invgate_fila_excel": 2, "notas": []},
        {"id": 100002, "sucursal": "Sucursal 013", "sucursal_num": "013", "estado": "Cerrado",
         "descripcion": "Ticket InvGate ", "origen": "InvGate", "invgate_ticket_id": "",
         "invgate_hoja": "Proveedor Uno", "invgate_fila_excel": 3, "notas": []},
    ]


class InvGateMigrationTests(unittest.TestCase):
    def test_prepare_cli_has_no_direct_apply_path(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "prepare_invgate_tickets_from_excel.py"), "--help"],
            check=True, capture_output=True, text=True,
        )
        self.assertNotIn("--apply", result.stdout)
        self.assertNotIn("--tickets-file", result.stdout)

    def test_headers_use_normalized_equality_not_substrings(self):
        headers = ["Fecha de solicitud", "Solicitud", "Demora de ticket", "Nro de Ticket", "SUCURSAL"]
        columns = prepare.resolve_columns(headers)
        self.assertEqual(columns["fecha_solicitud"], 0)
        self.assertEqual(columns["solicitud"], 1)
        self.assertEqual(columns["demora_ticket"], 2)
        self.assertEqual(columns["nro_ticket"], 3)
        self.assertEqual(prepare.column_index(headers, "solicitud"), 1)
        self.assertEqual(prepare.column_index(headers, "nro de ticket"), 3)

    def test_parser_excludes_catalog_and_preserves_operational_comments(self):
        with tempfile.TemporaryDirectory() as directory:
            workbook = Path(directory) / "fixture.xlsx"
            write_workbook(workbook)
            tickets, report = prepare.build_tickets(workbook, 1, only_open=False)
        self.assertEqual(report["total_tickets"], 1)
        self.assertEqual(report["skipped"]["fila_catalogo_o_metadato"], 1)
        ticket = tickets[0]
        self.assertEqual(ticket["descripcion"], "Reparar puerta")
        self.assertEqual(ticket["invgate_ticket_id"], "12345")
        self.assertEqual(ticket["actualizado"], ticket["creado"])
        notes = {note.get("campo"): note["texto"] for note in ticket["notas"] if note.get("tipo") == "comentario_operativo"}
        self.assertEqual(notes, {
            "fecha_realizacion_o_consulta": "se pidió repuesto", "demora_ticket": "2 días",
            "materiales": "bisagra", "ubicacion_materiales": "depósito",
        })

    def test_plan_apply_idempotence_and_rollback(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            workbook, original = base / "fixture.xlsx", base / "tickets.json"
            plan_path, corrected = base / "plan.json", base / "corrected.json"
            journal, restored = base / "journal.jsonl", base / "restored.json"
            write_workbook(workbook)
            before = input_tickets()
            write_json(original, before)
            plan = reconcile.make_plan(original, workbook, sha(original), strict_counts=False)
            self.assertEqual(plan["summary"]["safe_matches"], 1)
            self.assertEqual(plan["summary"]["spurious_catalog"], 1)
            self.assertEqual(plan["summary"]["safe_operations"], 1)
            self.assertEqual(plan["summary"]["spurious_operations"], 1)
            self.assertEqual(
                next(op for op in plan["operations"] if op["ticket_id"] == 100002)["kind"],
                "remove_spurious_catalog",
            )
            repeated = reconcile.make_plan(original, workbook, sha(original), strict_counts=False)
            self.assertEqual(
                [op["operation_id"] for op in repeated["operations"]],
                [op["operation_id"] for op in plan["operations"]],
            )
            write_json(plan_path, plan)
            result = reconcile.apply_plan(original, corrected, sha(original), plan_path, journal)
            self.assertEqual(result["applied"], 2)
            self.assertEqual(result["removed"], 1)
            after = json.loads(corrected.read_text(encoding="utf-8"))
            self.assertEqual(len(after), 1)
            self.assertEqual(after[0]["descripcion"], "Reparar puerta")
            self.assertEqual(after[0]["invgate_ticket_id"], "12345")
            self.assertEqual(after[0]["estado"], "Resuelto")
            self.assertEqual(after[0]["asignado"], "Operador actual")
            rows = [json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines()]
            removed = next(row for row in rows if row["kind"] == "remove_spurious_catalog")
            self.assertEqual(removed["before"], before[1])
            self.assertEqual(removed["original_index"], 1)
            self.assertIsNone(removed["after"])
            second = reconcile.make_plan(corrected, workbook, sha(corrected), strict_counts=False)
            self.assertEqual(second["summary"]["operations"], 0)
            self.assertEqual(second["summary"]["already_correct"], {"safe": 1})
            rolled = reconcile.rollback(corrected, restored, sha(corrected), journal)
            self.assertEqual(rolled["rolled_back"], 2)
            self.assertEqual(rolled["restored_removed"], 1)
            self.assertEqual(json.loads(restored.read_text(encoding="utf-8")), before)

    def test_duplicate_group_keeps_lowest_id_and_removes_later_ticket(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            workbook, original = base / "fixture.xlsx", base / "tickets.json"
            plan_path, corrected = base / "plan.json", base / "corrected.json"
            journal, restored = base / "journal.jsonl", base / "restored.json"
            write_workbook(workbook)
            duplicate = input_tickets()[0]
            second = dict(duplicate)
            second["id"] = 100003
            before = [second, duplicate]
            write_json(original, before)
            plan = reconcile.make_plan(original, workbook, sha(original), strict_counts=False)
            self.assertEqual(plan["summary"]["duplicate_groups"], 1)
            self.assertEqual(len(plan["duplicate_resolution"]), 1)
            resolution = plan["duplicate_resolution"][0]
            self.assertEqual(resolution["canonical_ticket_id"], 100001)
            self.assertEqual(resolution["removed_ticket_ids"], [100003])
            self.assertEqual(plan["summary"]["duplicate_canonical_corrections"], 1)
            self.assertEqual(plan["summary"]["duplicate_removals"], 1)
            kinds = {op["ticket_id"]: op["kind"] for op in plan["operations"]}
            self.assertEqual(kinds, {100001: "correct_safe_match", 100003: "remove_duplicate_ticket"})
            write_json(plan_path, plan)
            result = reconcile.apply_plan(original, corrected, sha(original), plan_path, journal)
            self.assertEqual((result["applied"], result["removed"]), (2, 1))
            after = json.loads(corrected.read_text(encoding="utf-8"))
            self.assertEqual([row["id"] for row in after], [100001])
            marker = after[0]["correccion_migracion"]["resolucion_duplicado"]
            self.assertEqual(marker["ticket_canonico_id"], 100001)
            self.assertEqual(marker["tickets_posteriores_eliminados"], [100003])
            second_plan = reconcile.make_plan(corrected, workbook, sha(corrected), strict_counts=False)
            self.assertEqual(second_plan["summary"]["operations"], 0)
            self.assertEqual(second_plan["summary"]["already_correct"], {"safe": 1})
            reconcile.rollback(corrected, restored, sha(corrected), journal)
            self.assertEqual(json.loads(restored.read_text(encoding="utf-8")), before)

    def test_removed_records_restore_at_exact_positions(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            workbook, original = base / "fixture.xlsx", base / "tickets.json"
            plan_path, corrected = base / "plan.json", base / "corrected.json"
            journal, restored = base / "journal.jsonl", base / "restored.json"
            write_workbook(workbook)
            first, spurious = input_tickets()
            middle = {"id": 999, "sucursal": "Sucursal 999", "estado": "Nuevo"}
            spurious_two = dict(spurious)
            spurious_two["id"] = 100004
            original_rows = [spurious, first, middle, spurious_two]
            write_json(original, original_rows)
            plan = reconcile.make_plan(original, workbook, sha(original), strict_counts=False)
            self.assertEqual([op["kind"] for op in plan["operations"]].count("remove_spurious_catalog"), 2)
            write_json(plan_path, plan)
            reconcile.apply_plan(original, corrected, sha(original), plan_path, journal)
            self.assertEqual([row["id"] for row in json.loads(corrected.read_text())], [100001, 999])
            reconcile.rollback(corrected, restored, sha(corrected), journal)
            self.assertEqual(json.loads(restored.read_text(encoding="utf-8")), original_rows)

    def test_strict_audit_accepts_only_initial_or_fully_applied_state(self):
        initial = {
            "safe_matches": 96, "spurious_catalog": 56,
            "duplicate_groups": 3, "real_excel_rows": 1327,
        }
        state, mismatches = reconcile.audit_state(
            initial, [{}] * 146, reconcile.Counter(), 6
        )
        self.assertEqual((state, mismatches), ("initial", {}))

        applied = dict(initial, safe_matches=93, spurious_catalog=0, duplicate_groups=0)
        state, mismatches = reconcile.audit_state(
            applied, [], reconcile.Counter({"safe": 93}), 0
        )
        self.assertEqual((state, mismatches), ("fully_applied", {}))

        partial_cases = [
            (dict(initial, spurious_catalog=1), [], reconcile.Counter({"safe": 93}), 0),
            (applied, [{}], reconcile.Counter({"safe": 93}), 0),
            (applied, [], reconcile.Counter({"safe": 92}), 0),
            (applied, [], reconcile.Counter({"safe": 93}), 1),
        ]
        for observed, operations, already_correct, duplicate_count in partial_cases:
            with self.subTest(observed=observed, operations=len(operations), already_correct=already_correct, duplicate_count=duplicate_count):
                state, mismatches = reconcile.audit_state(
                    observed, operations, already_correct, duplicate_count
                )
                self.assertEqual(state, "mismatch")
                self.assertTrue(mismatches)

    def test_sha_precondition_and_rollback_after_guard(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            workbook, original = base / "fixture.xlsx", base / "tickets.json"
            plan_path, corrected = base / "plan.json", base / "corrected.json"
            journal, tampered, restored = base / "journal.jsonl", base / "tampered.json", base / "restored.json"
            write_workbook(workbook)
            write_json(original, input_tickets())
            with self.assertRaisesRegex(ValueError, "precondición SHA"):
                reconcile.make_plan(original, workbook, "0" * 64, strict_counts=False)
            write_json(plan_path, reconcile.make_plan(original, workbook, sha(original), strict_counts=False))
            reconcile.apply_plan(original, corrected, sha(original), plan_path, journal)
            value = json.loads(corrected.read_text(encoding="utf-8"))
            value[0]["descripcion"] = "cambio posterior"
            write_json(tampered, value)
            with self.assertRaisesRegex(ValueError, "precondición after global"):
                reconcile.rollback(tampered, restored, sha(tampered), journal)
            self.assertFalse(restored.exists())

    def test_in_place_apply_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            workbook, original = base / "fixture.xlsx", base / "tickets.json"
            plan_path, journal = base / "plan.json", base / "journal.jsonl"
            write_workbook(workbook)
            write_json(original, input_tickets())
            write_json(plan_path, reconcile.make_plan(original, workbook, sha(original), strict_counts=False))
            with self.assertRaisesRegex(ValueError, "distintas"):
                reconcile.apply_plan(original, original, sha(original), plan_path, journal)
            output = base / "output.json"
            with self.assertRaisesRegex(ValueError, "distintas"):
                reconcile.apply_plan(original, output, sha(original), plan_path, original)


if __name__ == "__main__":
    unittest.main()
