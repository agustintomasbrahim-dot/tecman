#!/usr/bin/env python3
"""Plan, apply to a new local file, or roll back the InvGate correction.

Safety properties:
* plan/dry-run is the default and all inputs are explicit;
* an exact SHA-256 precondition is mandatory;
* apply/rollback refuse in-place writes and never use network endpoints;
* operations and IDs are deterministic, with full before/after journals;
* only exact sheet + Excel row + numeric branch matches are corrected.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from prepare_invgate_tickets_from_excel import (
    build_tickets,
    clean,
    is_numeric_ticket,
    norm_sucursal,
)

VERSION = "invgate-correction-v3"
AUDIT_EXPECTED = {
    "safe_matches": 96,
    "spurious_catalog": 56,
    "duplicate_groups": 3,
    "ambiguous_excluded": 3,
    "without_candidate_excluded": 1228,
    "real_excel_rows": 1327,
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def object_hash(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise


def atomic_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise


def read_tickets(path: Path) -> list[dict[str, Any]]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError("--input debe ser un JSON array de tickets")
    ids = [str(item.get("id")) for item in value]
    if len(ids) != len(set(ids)):
        raise ValueError("--input contiene IDs duplicados")
    return value


def numeric_branch(ticket: dict[str, Any]) -> str:
    value = clean(ticket.get("sucursal_num"))
    if value:
        _, branch = norm_sucursal(value)
        if branch:
            return branch
    _, branch = norm_sucursal(ticket.get("sucursal"))
    return branch


def source_key(ticket: dict[str, Any]) -> tuple[str, int, str] | None:
    sheet = clean(ticket.get("invgate_hoja"))
    row = ticket.get("invgate_fila_excel")
    branch = numeric_branch(ticket)
    if not sheet or isinstance(row, bool) or not isinstance(row, int) or not branch:
        return None
    return sheet, row, branch


def correction_note(ticket: dict[str, Any], kind: str) -> dict[str, Any]:
    return {
        "autor": "Corrección migración InvGate",
        "fecha": "2026-09-24T00:00:00",
        "tipo": kind,
        "texto": (
            f"{VERSION}: fuente verificada por hoja {clean(ticket.get('invgate_hoja'))}, "
            f"fila {ticket.get('invgate_fila_excel')} y sucursal {numeric_branch(ticket)}."
        ),
    }


def append_unique_note(notes: Any, note: dict[str, Any]) -> list[dict[str, Any]]:
    result = copy.deepcopy(notes) if isinstance(notes, list) else []
    marker = (note.get("tipo"), note.get("texto"))
    if not any(isinstance(existing, dict) and (existing.get("tipo"), existing.get("texto")) == marker for existing in result):
        result.append(note)
    return result


def corrected_ticket(before: dict[str, Any], source: dict[str, Any], duplicate_ids: list[Any]) -> dict[str, Any]:
    after = copy.deepcopy(before)
    for field in (
        "descripcion", "invgate_ticket_id", "invgate_estado_original", "proveedor_presupuesto",
        "provincia_origen", "materiales_origen", "ubicacion_materiales_origen",
    ):
        after[field] = copy.deepcopy(source.get(field, ""))
    # Preserve live workflow fields. Reconstructing migration metadata must not
    # reopen a resolved ticket or replace an assignment made after import.
    notes = append_unique_note(after.get("notas"), correction_note(before, "correccion_migracion"))
    for note in source.get("notas", []):
        if isinstance(note, dict) and note.get("tipo") == "comentario_operativo":
            notes = append_unique_note(notes, note)
    after["notas"] = notes
    marker: dict[str, Any] = {
        "version": VERSION,
        "clasificacion": "coincidencia_segura",
        "clave_fuente": {
            "hoja": clean(before.get("invgate_hoja")),
            "fila": before.get("invgate_fila_excel"),
            "sucursal": numeric_branch(before),
        },
    }
    if duplicate_ids:
        marker["resolucion_duplicado"] = {
            "criterio": "conservar_id_tecman_menor",
            "ticket_canonico_id": before.get("id"),
            "ticket_ids_grupo": sorted(duplicate_ids, key=lambda value: str(value)),
            "tickets_posteriores_eliminados": [
                value for value in sorted(duplicate_ids, key=lambda value: str(value))
                if str(value) != str(before.get("id"))
            ],
        }
    elif isinstance(before.get("correccion_migracion"), dict):
        existing_resolution = before["correccion_migracion"].get("resolucion_duplicado")
        if isinstance(existing_resolution, dict) and str(existing_resolution.get("ticket_canonico_id")) == str(before.get("id")):
            # After later duplicates have been removed, preserve the deterministic
            # resolution evidence on the surviving canonical ticket.
            marker["resolucion_duplicado"] = copy.deepcopy(existing_resolution)
    after["correccion_migracion"] = marker
    return after


def operation(kind: str, before: dict[str, Any], after: dict[str, Any] | None, original_index: int) -> dict[str, Any]:
    identity = {
        "version": VERSION,
        "kind": kind,
        "ticket_id": before.get("id"),
        "source": source_key(before),
        "original_index": original_index,
        "before_sha256": object_hash(before),
        "after_sha256": object_hash(after),
    }
    return {
        "operation_id": hashlib.sha256(canonical_bytes(identity)).hexdigest(),
        "kind": kind,
        "ticket_id": before.get("id"),
        "original_index": original_index,
        "before_sha256": identity["before_sha256"],
        "after_sha256": identity["after_sha256"],
        "before": before,
        "after": after,
    }


def id_order_hash(tickets: list[dict[str, Any]]) -> str:
    return object_hash([str(ticket.get("id")) for ticket in tickets])


def ticket_id_order(value: Any) -> tuple[int, int | str]:
    text = clean(value)
    try:
        return (0, int(text))
    except ValueError:
        return (1, text)


def audit_state(
    observed: dict[str, int],
    operations: list[dict[str, Any]],
    already_correct: Counter[str],
    duplicate_ticket_count: int,
) -> tuple[str, dict[str, dict[str, int]]]:
    """Classify only the audited initial or fully-applied snapshots as strict."""
    mismatches = {
        key: {"expected": expected, "observed": observed.get(key)}
        for key, expected in AUDIT_EXPECTED.items()
        if key in observed and observed.get(key) != expected
    }
    if not mismatches:
        return "initial", {}
    safe_operations = sum(op.get("kind") == "correct_safe_match" for op in operations)
    fully_applied = (
        mismatches == {
            "safe_matches": {"expected": AUDIT_EXPECTED["safe_matches"], "observed": 93},
            "spurious_catalog": {"expected": AUDIT_EXPECTED["spurious_catalog"], "observed": 0},
            "duplicate_groups": {"expected": AUDIT_EXPECTED["duplicate_groups"], "observed": 0},
        }
        and duplicate_ticket_count == 0
        and already_correct == Counter({"safe": 93})
        and len(operations) == 0
        and safe_operations == 0
    )
    return ("fully_applied", {}) if fully_applied else ("mismatch", mismatches)


def make_plan(input_path: Path, excel_path: Path, expected_sha: str, strict_counts: bool) -> dict[str, Any]:
    actual_sha = sha256_file(input_path)
    if actual_sha != expected_sha.lower():
        raise ValueError(f"precondición SHA falló: esperado {expected_sha.lower()}, actual {actual_sha}")
    tickets = read_tickets(input_path)
    input_indexes = {str(ticket.get("id")): index for index, ticket in enumerate(tickets)}
    source_rows, source_report = build_tickets(excel_path, start_id=1, only_open=False)
    source_index = {(clean(row["invgate_hoja"]), int(row["invgate_fila_excel"]), numeric_branch(row)): row for row in source_rows}

    candidates: list[tuple[dict[str, Any], dict[str, Any]]] = []
    spurious: list[dict[str, Any]] = []
    for ticket in tickets:
        if ticket.get("origen") != "InvGate" or clean(ticket.get("invgate_hoja")) == "CEYH Hoja 1":
            continue
        key = source_key(ticket)
        if key and key in source_index:
            candidates.append((ticket, source_index[key]))
        elif key and not clean(ticket.get("invgate_ticket_id")):
            # Within the audited workbook scope, unmatched provenance plus a blank
            # InvGate ID is a supplier/branch directory row, never a real request.
            spurious.append(ticket)

    duplicate_map: dict[tuple[str, str], list[Any]] = defaultdict(list)
    for before, source in candidates:
        duplicate_map[(clean(source.get("invgate_ticket_id")), numeric_branch(source))].append(before.get("id"))
    duplicate_groups = {key: ids for key, ids in duplicate_map.items() if key[0] and len(ids) > 1}

    operations = []
    already_correct = Counter()
    duplicate_ticket_ids = {str(ticket_id) for ids in duplicate_groups.values() for ticket_id in ids}
    canonical_ids = {
        str(min(ids, key=ticket_id_order)) for ids in duplicate_groups.values()
    }
    removed_duplicate_ids = duplicate_ticket_ids - canonical_ids
    for before, source in sorted(candidates, key=lambda pair: str(pair[0].get("id"))):
        ticket_id = str(before.get("id"))
        if ticket_id in removed_duplicate_ids:
            continue
        group_ids = next(
            (ids for ids in duplicate_groups.values() if ticket_id in {str(value) for value in ids}),
            [],
        )
        after = corrected_ticket(before, source, group_ids)
        if object_hash(before) == object_hash(after):
            already_correct["safe"] += 1
        else:
            operations.append(operation("correct_safe_match", before, after, input_indexes[str(before.get("id"))]))
    candidates_by_id = {str(before.get("id")): before for before, _source in candidates}
    for ticket_id in sorted(removed_duplicate_ids, key=ticket_id_order):
        before = candidates_by_id[ticket_id]
        operations.append(operation(
            "remove_duplicate_ticket", before, None, input_indexes[ticket_id]
        ))
    for before in sorted(spurious, key=lambda item: str(item.get("id"))):
        operations.append(operation(
            "remove_spurious_catalog", before, None, input_indexes[str(before.get("id"))]
        ))

    observed = {
        "safe_matches": len(candidates),
        "spurious_catalog": len(spurious),
        "duplicate_groups": len(duplicate_groups),
        "real_excel_rows": source_report["total_tickets"] + source_report.get("skipped", {}).get("fila_sin_sucursal", 0),
    }
    audit_status, mismatches = audit_state(
        observed, operations, already_correct, len(duplicate_ticket_ids)
    )
    if strict_counts and audit_status == "mismatch":
        raise ValueError(f"conteos de auditoría no coinciden: {json.dumps(mismatches, ensure_ascii=False, sort_keys=True)}")

    return {
        "schema": "tecman.invgate-correction-plan/v1",
        "version": VERSION,
        "mode": "dry-run",
        "input": str(input_path),
        "input_sha256": actual_sha,
        "excel": str(excel_path),
        "excel_sha256": sha256_file(excel_path),
        "selection_rule": "igualdad exacta de hoja + fila Excel + sucursal numérica",
        "summary": {
            **observed,
            "ambiguous_excluded": AUDIT_EXPECTED["ambiguous_excluded"],
            "without_candidate_excluded": AUDIT_EXPECTED["without_candidate_excluded"],
            "historical_closed_not_imported": "excluded",
            "audit_state": audit_status,
            "operations": len(operations),
            "safe_operations": sum(op["kind"] == "correct_safe_match" for op in operations),
            "duplicate_canonical_corrections": len(canonical_ids),
            "duplicate_removals": sum(op["kind"] == "remove_duplicate_ticket" for op in operations),
            "total_removals": sum(op["kind"] in {"remove_spurious_catalog", "remove_duplicate_ticket"} for op in operations),
            "spurious_operations": sum(op["kind"] == "remove_spurious_catalog" for op in operations),
            "already_correct": dict(already_correct),
            "audit_count_mismatches": mismatches,
        },
        "duplicate_resolution": [
            {
                "invgate_ticket_id": key[0],
                "sucursal": key[1],
                "ticket_ids": sorted(ids, key=ticket_id_order),
                "canonical_ticket_id": min(ids, key=ticket_id_order),
                "removed_ticket_ids": [value for value in sorted(ids, key=ticket_id_order) if value != min(ids, key=ticket_id_order)],
                "criterion": "lowest_numeric_tecman_id",
            }
            for key, ids in sorted(duplicate_groups.items())
        ],
        "operations": operations,
    }


def ensure_distinct_paths(**paths: Path) -> None:
    resolved: dict[Path, str] = {}
    for label, path in paths.items():
        current = path.resolve()
        if current in resolved:
            raise ValueError(f"rutas de salida/entrada deben ser distintas: {resolved[current]} y {label}")
        resolved[current] = label


def apply_plan(input_path: Path, output_path: Path, expected_sha: str, plan_path: Path, journal_path: Path) -> dict[str, Any]:
    ensure_distinct_paths(input=input_path, output=output_path, plan=plan_path, journal=journal_path)
    actual_sha = sha256_file(input_path)
    if actual_sha != expected_sha.lower():
        raise ValueError(f"precondición SHA falló: esperado {expected_sha.lower()}, actual {actual_sha}")
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if plan.get("input_sha256") != actual_sha:
        raise ValueError("el plan no corresponde al SHA del input")
    tickets = read_tickets(input_path)
    indexes = {str(ticket.get("id")): i for i, ticket in enumerate(tickets)}
    operations = plan.get("operations", [])
    if not isinstance(operations, list):
        raise ValueError("operations inválidas en plan")
    seen: set[str] = set()
    for op in operations:
        key = str(op.get("ticket_id"))
        if key in seen:
            raise ValueError(f"operación duplicada para ticket {key}")
        seen.add(key)
        if key not in indexes:
            raise ValueError(f"ticket ausente al aplicar: {key}")
        current_index = indexes[key]
        current = tickets[current_index]
        if current_index != op.get("original_index"):
            raise ValueError(f"posición original divergente para ticket {key}")
        if object_hash(current) != op.get("before_sha256"):
            raise ValueError(f"precondición before falló para ticket {key}")
        if object_hash(op.get("after")) != op.get("after_sha256"):
            raise ValueError(f"after corrupto para ticket {key}")
        if op.get("kind") in {"remove_spurious_catalog", "remove_duplicate_ticket"}:
            if op.get("after") is not None:
                raise ValueError(f"eliminación con after no nulo para ticket {key}")
        elif op.get("kind") != "correct_safe_match":
            raise ValueError(f"tipo de operación no permitido: {op.get('kind')}")

    result = copy.deepcopy(tickets)
    for op in operations:
        if op.get("kind") == "correct_safe_match":
            result[indexes[str(op.get("ticket_id"))]] = copy.deepcopy(op["after"])
    removed_ids = {
        str(op.get("ticket_id")) for op in operations
        if op.get("kind") in {"remove_spurious_catalog", "remove_duplicate_ticket"}
    }
    result = [ticket for ticket in result if str(ticket.get("id")) not in removed_ids]

    guards = {
        "input_ticket_count": len(tickets),
        "output_ticket_count": len(result),
        "input_semantic_sha256": object_hash(tickets),
        "output_semantic_sha256": object_hash(result),
        "input_id_order_sha256": id_order_hash(tickets),
        "output_id_order_sha256": id_order_hash(result),
    }
    journal = []
    for op in operations:
        row = copy.deepcopy(op)
        row["journal_guards"] = guards
        journal.append(row)
    atomic_json(output_path, result)
    atomic_jsonl(journal_path, journal)
    return {
        "applied": len(journal),
        "removed": len(removed_ids),
        "output": str(output_path),
        "output_sha256": sha256_file(output_path),
        "journal": str(journal_path),
    }


def rollback(input_path: Path, output_path: Path, expected_sha: str, journal_path: Path) -> dict[str, Any]:
    ensure_distinct_paths(input=input_path, output=output_path, journal=journal_path)
    actual_sha = sha256_file(input_path)
    if actual_sha != expected_sha.lower():
        raise ValueError(f"precondición SHA falló: esperado {expected_sha.lower()}, actual {actual_sha}")
    tickets = read_tickets(input_path)
    rows = [json.loads(line) for line in journal_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not rows:
        raise ValueError("journal vacío")
    guards = rows[0].get("journal_guards")
    if not isinstance(guards, dict) or any(row.get("journal_guards") != guards for row in rows):
        raise ValueError("guardas globales del journal ausentes o divergentes")
    if len(tickets) != guards.get("output_ticket_count") or object_hash(tickets) != guards.get("output_semantic_sha256") or id_order_hash(tickets) != guards.get("output_id_order_sha256"):
        raise ValueError("precondición after global falló: la copia corregida divergió")

    result = copy.deepcopy(tickets)
    indexes = {str(ticket.get("id")): i for i, ticket in enumerate(result)}
    safe_rows = [row for row in rows if row.get("kind") == "correct_safe_match"]
    remove_rows = [
        row for row in rows
        if row.get("kind") in {"remove_spurious_catalog", "remove_duplicate_ticket"}
    ]
    if len(safe_rows) + len(remove_rows) != len(rows):
        raise ValueError("journal contiene tipos de operación no permitidos")

    for op in reversed(safe_rows):
        key = str(op.get("ticket_id"))
        if key not in indexes:
            raise ValueError(f"ticket ausente al revertir: {key}")
        current = result[indexes[key]]
        if object_hash(current) != op.get("after_sha256"):
            raise ValueError(f"precondición after falló para ticket {key}")
        if object_hash(op.get("before")) != op.get("before_sha256"):
            raise ValueError(f"before corrupto para ticket {key}")
        result[indexes[key]] = copy.deepcopy(op["before"])

    existing_ids = {str(ticket.get("id")) for ticket in result}
    for op in sorted(remove_rows, key=lambda row: row.get("original_index")):
        key = str(op.get("ticket_id"))
        if key in existing_ids:
            raise ValueError(f"ticket eliminado reapareció antes del rollback: {key}")
        before = op.get("before")
        if object_hash(before) != op.get("before_sha256"):
            raise ValueError(f"before corrupto para ticket {key}")
        index = op.get("original_index")
        if not isinstance(index, int) or index < 0 or index > len(result):
            raise ValueError(f"posición original inválida para ticket {key}")
        result.insert(index, copy.deepcopy(before))
        existing_ids.add(key)

    if len(result) != guards.get("input_ticket_count") or object_hash(result) != guards.get("input_semantic_sha256") or id_order_hash(result) != guards.get("input_id_order_sha256"):
        raise ValueError("rollback no reconstruyó exactamente la semántica y posición originales")
    atomic_json(output_path, result)
    return {
        "rolled_back": len(rows),
        "restored_removed": len(remove_rows),
        "output": str(output_path),
        "output_sha256": sha256_file(output_path),
    }

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="explicit local tickets.json copy")
    parser.add_argument("--expected-sha256", required=True, help="mandatory SHA-256 precondition for --input")
    parser.add_argument("--excel", type=Path, help="explicit source workbook (required for planning)")
    parser.add_argument("--plan-output", type=Path, help="where to write the dry-run plan")
    parser.add_argument("--strict-audit-counts", action="store_true")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="apply an existing plan to a distinct output file")
    mode.add_argument("--rollback", action="store_true", help="rollback a journal to a distinct output file")
    parser.add_argument("--plan", type=Path, help="existing plan for --apply")
    parser.add_argument("--journal", type=Path, help="journal output for --apply or input for --rollback")
    parser.add_argument("--output", type=Path, help="distinct local output for apply/rollback")
    args = parser.parse_args()

    try:
        if args.apply:
            if not all((args.plan, args.journal, args.output)):
                parser.error("--apply requiere --plan, --journal y --output")
            result = apply_plan(args.input, args.output, args.expected_sha256, args.plan, args.journal)
        elif args.rollback:
            if not all((args.journal, args.output)):
                parser.error("--rollback requiere --journal y --output")
            result = rollback(args.input, args.output, args.expected_sha256, args.journal)
        else:
            if not args.excel or not args.plan_output:
                parser.error("plan/dry-run requiere --excel y --plan-output")
            ensure_distinct_paths(input=args.input, excel=args.excel, plan_output=args.plan_output)
            result = make_plan(args.input, args.excel, args.expected_sha256, args.strict_audit_counts)
            atomic_json(args.plan_output, result)
            result = {"plan": str(args.plan_output), "summary": result["summary"]}
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
