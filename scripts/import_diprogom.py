#!/usr/bin/env python3
"""Parse and safely reconcile a local Diprogom XLS against matafuegos.json.

Dry-run is the default. All modes require an explicit local inventory path and
its SHA-256. Apply and rollback write distinct paths and never use the network.
"""
from __future__ import annotations

import argparse
import base64
import copy
import datetime as dt
import hashlib
import json
import os
import re
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import xlrd

VERSION = "diprogom-import-v2"
XLRD_VERSION = "2.0.1"
PROVIDER = "Diprogom"
PROVIDER_ORIGIN = "diprogom_xls"
EXPECTED_XLS_SHA256 = "72c446190dd5c9b7b1451b86e2efabcbf837dc6763391fe5c6dbac82a3000e92"
EXPECTED_ROWS = 483
EXPECTED_NUMBERED_ROWS = 469
EXPECTED_NUMBERED_BRANCHES = 30
EXPECTED_ACTIVE_ROWS = 358
EXPECTED_ACTIVE_BRANCHES = 25
CONFLICT_BRANCHES = {"051": 13, "156": 23}
GREEN_FILL_INDEX = 49
GREEN_FILL_RGB = (51, 204, 204)
INACTIVE_GREEN_BRANCHES = {"167": 19, "183": 29, "213": 27}
EXPECTED_INACTIVE_GREEN_ROWS = 75
PENDING_LABEL = "PARQUE INDUSTRIAL MORZAT"
PENDING_ADDRESS = "MORZAT S/N"
EXPECTED_PENDING_ROWS = 14
SHEET_NAME = "Hoja1"
TITLE = " Extintores por Clientes"
HEADERS = ("Cliente", "Nombre Suc", "Domicilio", "Vto Carga", "Matafuego", "Tarjeta", "Iram", "Fabric", "Tipo", "Capac")
TYPE_ALIASES = {"POLVO ABC": "ABC", "CO2": "CO2", "HCFC - 123": "HCFC-123", "HCFC-123": "HCFC-123"}
ALLOWED_TYPES = {"ABC", "CO2", "HCFC-123"}
ALLOWED_CAPACITIES = {"2.5 KG", "3.5 KG", "5 KG", "10 KG", "25 KG", "50 KG"}
BRANCH_RE = re.compile(r"\b(?:SUC(?:URSAL)?|LOCAL)\s*[-:]?\s*0*(\d{1,3})\b", re.IGNORECASE)
OPERATIONAL_KEYS = {
    "fecha_vencimiento_manual", "historial", "historial_mantenimientos", "estado_manual",
    "actualizado_por_sucursal", "actualizado_por_proveedor", "actualizado_at",
    "observacion_mantenimiento", "fecha_vencimiento_anterior", "fecha_vencimiento_original",
    "visita_id", "encontrado", "estado_fisico", "trabajo_realizado",
}


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def object_hash(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def atomic_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def clean_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def normalize_identifier(value: Any, label: str) -> str:
    if isinstance(value, bool) or value in (None, ""):
        raise ValueError(f"{label} vacío o inválido")
    if isinstance(value, float):
        if not value.is_integer():
            raise ValueError(f"{label} no entero: {value!r}")
        return str(int(value))
    text = str(value).strip()
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    if not text or not re.fullmatch(r"[A-Za-z0-9-]+", text):
        raise ValueError(f"{label} inválido: {value!r}")
    return text


def normalize_type(value: Any) -> str:
    text = clean_text(value).upper()
    normalized = TYPE_ALIASES.get(text, text)
    if normalized not in ALLOWED_TYPES:
        raise ValueError(f"tipo de matafuego no autorizado: {value!r}")
    return normalized


def normalize_capacity(value: Any) -> str:
    if isinstance(value, bool) or value in (None, ""):
        raise ValueError(f"capacidad inválida: {value!r}")
    text = str(value).strip().upper().replace(",", ".")
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(?:KG)?", text)
    if not match:
        raise ValueError(f"capacidad inválida: {value!r}")
    number = float(match.group(1))
    normalized = f"{number:g} KG"
    if normalized not in ALLOWED_CAPACITIES:
        raise ValueError(f"capacidad no autorizada: {value!r}")
    return normalized


def monthly_date(value: Any) -> str:
    text = str(value or "").strip()
    match = re.fullmatch(r"(0[1-9]|1[0-2])-(\d{2})\.", text)
    if not match:
        raise ValueError(f"vencimiento mensual inválido: {value!r}")
    return dt.date(2000 + int(match.group(2)), int(match.group(1)), 1).isoformat()


def branch_from_values(name: Any, address: Any) -> tuple[str | None, str]:
    normalized_name = clean_text(name)
    name_match = BRANCH_RE.search(normalized_name)
    if name_match:
        return f"{int(name_match.group(1)):03d}", "nombre_suc"
    if not normalized_name:
        address_match = BRANCH_RE.search(clean_text(address))
        if address_match:
            return f"{int(address_match.group(1)):03d}", "domicilio_fallback"
    return None, "sin_numero"


def green_fill_marker(workbook: Any, sheet: Any, row_index: int) -> bool:
    """Return whether the whole source row carries Diprogom's green marker.

    The BIFF palette index alone is workbook-specific, so both the explicit
    index and its RGB value are required. A partial green row is rejected
    rather than silently changing the scope of a branch.
    """
    if workbook.colour_map.get(GREEN_FILL_INDEX) != GREEN_FILL_RGB:
        raise ValueError(
            f"paleta XLS inesperada para fill {GREEN_FILL_INDEX}: "
            f"{workbook.colour_map.get(GREEN_FILL_INDEX)!r}"
        )
    marked: list[bool] = []
    for column_index in range(sheet.ncols):
        cell = sheet.cell(row_index, column_index)
        background = workbook.xf_list[cell.xf_index].background
        marked.append(
            background.fill_pattern != 0
            and background.pattern_colour_index == GREEN_FILL_INDEX
            and workbook.colour_map.get(background.pattern_colour_index) == GREEN_FILL_RGB
        )
    if any(marked) and not all(marked):
        raise ValueError(f"fila {row_index + 1}: marcador verde parcial")
    return all(marked)


def parse_sheet(sheet: Any, source_path: Path, source_sha: str, workbook: Any) -> dict[str, Any]:
    if sheet.nrows < 3 or sheet.ncols != len(HEADERS):
        raise ValueError(f"dimensiones inesperadas: {sheet.nrows}x{sheet.ncols}")
    if tuple(sheet.row_values(0)) != (TITLE,) + ("",) * 9:
        raise ValueError("título XLS inesperado")
    if tuple(sheet.row_values(1)) != ("",) * 10:
        raise ValueError("segunda fila XLS inesperada")
    actual_headers = tuple(sheet.row_values(2))
    if actual_headers != HEADERS:
        raise ValueError(f"encabezados no coinciden exactamente: {actual_headers!r}")

    rows: list[dict[str, Any]] = []
    identifiers: set[str] = set()
    fallback_rows = 0
    green_marker_rows: list[dict[str, Any]] = []
    for row_index in range(3, sheet.nrows):
        values = sheet.row_values(row_index)
        row_number = row_index + 1
        if len(values) != 10 or not any(value not in (None, "") for value in values):
            raise ValueError(f"fila {row_number}: vacía o incompleta")
        if clean_text(values[0]) != "DABRA S.A.":
            raise ValueError(f"fila {row_number}: cliente inesperado")
        extinguisher = normalize_identifier(values[4], f"fila {row_number}: Matafuego")
        if extinguisher in identifiers:
            raise ValueError(f"Matafuego duplicado: {extinguisher}")
        identifiers.add(extinguisher)
        branch, branch_source = branch_from_values(values[1], values[2])
        if branch_source == "domicilio_fallback":
            fallback_rows += 1
        pending = branch is None
        name = clean_text(values[1])
        address = clean_text(values[2])
        if pending and (name != PENDING_LABEL or address != PENDING_ADDRESS):
            raise ValueError(f"fila {row_number}: sucursal no identificable fuera de Morzat")
        green_marker = green_fill_marker(workbook, sheet, row_index)
        parsed_row = {
            "row": row_number,
            "sucursal_num": branch,
            "branch_source": branch_source,
            "pending": pending,
            "nro_extintor": extinguisher,
            "fecha_vencimiento_proveedor": monthly_date(values[3]),
            "tipo": normalize_type(values[8]),
            "capacidad": normalize_capacity(values[9]),
            "green_marker": green_marker,
        }
        rows.append(parsed_row)
        if green_marker:
            green_marker_rows.append(parsed_row)

    numbered = [row for row in rows if row["sucursal_num"]]
    pending = [row for row in rows if row["pending"]]
    branch_counts = Counter(row["sucursal_num"] for row in numbered)
    conflict_counts = {branch: branch_counts.get(branch, 0) for branch in sorted(CONFLICT_BRANCHES)}
    marker_branches = {row["sucursal_num"] for row in green_marker_rows}
    if None in marker_branches:
        raise ValueError("marcador verde en fila sin sucursal")
    for row in numbered:
        row["inactive_green"] = row["sucursal_num"] in marker_branches
    inactive_green = [row for row in numbered if row["inactive_green"]]
    inactive_green_counts = Counter(row["sucursal_num"] for row in inactive_green)
    marker_counts = Counter(row["sucursal_num"] for row in green_marker_rows)
    first_rows = {branch: min(row["row"] for row in numbered if row["sucursal_num"] == branch) for branch in marker_branches}
    marker_first_rows = all(row["row"] == first_rows[row["sucursal_num"]] for row in green_marker_rows)
    active = [
        row for row in numbered
        if row["sucursal_num"] not in CONFLICT_BRANCHES and not row["inactive_green"]
    ]
    active_branches = sorted({row["sucursal_num"] for row in active})
    validations = {
        "rows": len(rows) == EXPECTED_ROWS,
        "unique_extinguisher_ids": len(identifiers) == EXPECTED_ROWS,
        "numbered_rows": len(numbered) == EXPECTED_NUMBERED_ROWS,
        "numbered_branches": len(branch_counts) == EXPECTED_NUMBERED_BRANCHES,
        "conflict_counts": conflict_counts == CONFLICT_BRANCHES,
        "pending_rows": len(pending) == EXPECTED_PENDING_ROWS,
        "fallback_214_rows": fallback_rows == 9 and branch_counts.get("214") == 9,
        "green_palette": workbook.colour_map.get(GREEN_FILL_INDEX) == GREEN_FILL_RGB,
        "green_marker_branches": marker_branches == set(INACTIVE_GREEN_BRANCHES),
        "green_marker_once_per_branch": marker_counts == {branch: 1 for branch in INACTIVE_GREEN_BRANCHES},
        "green_marker_first_row": marker_first_rows,
        "inactive_green_counts": dict(inactive_green_counts) == INACTIVE_GREEN_BRANCHES,
        "inactive_green_rows": len(inactive_green) == EXPECTED_INACTIVE_GREEN_ROWS,
        "active_rows": len(active) == EXPECTED_ACTIVE_ROWS,
        "active_branches": len(active_branches) == EXPECTED_ACTIVE_BRANCHES,
    }
    if not all(validations.values()):
        raise ValueError(f"conteos Diprogom inesperados: {validations!r}")
    return {
        "schema": "tecman.diprogom-source/v1",
        "xls": str(source_path),
        "xls_sha256": source_sha,
        "rows": rows,
        "summary": {
            "rows": len(rows),
            "unique_extinguisher_ids": len(identifiers),
            "numbered_rows": len(numbered),
            "numbered_branches": len(branch_counts),
            "active_rows": len(active),
            "active_branches": len(active_branches),
            "inactive_green_rows": len(inactive_green),
            "inactive_green_branches": dict(sorted(inactive_green_counts.items())),
            "green_fill_index": GREEN_FILL_INDEX,
            "green_fill_rgb": list(GREEN_FILL_RGB),
            "green_marker_rows": [row["row"] for row in green_marker_rows],
            "conflict_rows": sum(conflict_counts.values()),
            "conflict_branches": conflict_counts,
            "pending_rows": len(pending),
            "pending_label": PENDING_LABEL,
            "fallback_214_rows": fallback_rows,
            "count_validation": "ok",
        },
        "active_branch_numbers": active_branches,
        "inactive_green_branch_numbers": sorted(marker_branches),
    }


def parse_xls(path: Path, *, expected_source_sha: str = EXPECTED_XLS_SHA256) -> dict[str, Any]:
    if getattr(xlrd, "__version__", None) != XLRD_VERSION:
        raise ValueError(f"se requiere xlrd=={XLRD_VERSION}")
    actual_sha = sha256_file(path)
    if actual_sha != expected_source_sha.lower():
        raise ValueError(f"SHA XLS inesperado: esperado {expected_source_sha.lower()}, actual {actual_sha}")
    workbook = xlrd.open_workbook(str(path), on_demand=True, formatting_info=True)
    try:
        if workbook.sheet_names() != [SHEET_NAME]:
            raise ValueError(f"hojas inesperadas: {workbook.sheet_names()!r}")
        return parse_sheet(workbook.sheet_by_name(SHEET_NAME), path, actual_sha, workbook)
    finally:
        workbook.release_resources()


def load_inventory(path: Path, expected_sha: str) -> tuple[dict[str, Any], str]:
    actual = sha256_file(path)
    if actual != expected_sha.lower():
        raise ValueError(f"precondición SHA falló: esperado {expected_sha.lower()}, actual {actual}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("matafuegos"), list) or not all(isinstance(item, dict) for item in value["matafuegos"]):
        raise ValueError("--input debe ser matafuegos.json con array matafuegos")
    ids = [str(item.get("id")) for item in value["matafuegos"]]
    if any(item_id in ("", "None") for item_id in ids) or len(ids) != len(set(ids)):
        raise ValueError("IDs de inventario ausentes o duplicados")
    return value, actual


def normalize_branch(value: Any) -> str:
    match = re.search(r"(\d{1,3})", str(value or ""))
    if not match:
        raise ValueError(f"sucursal inválida: {value!r}")
    return f"{int(match.group(1)):03d}"


def item_key(item: dict[str, Any]) -> tuple[str, str, str] | None:
    try:
        branch = normalize_branch(item.get("sucursal_num") or item.get("sucursal"))
        kind = normalize_type(item.get("tipo"))
        capacity = normalize_capacity(item.get("capacidad"))
    except ValueError:
        return None
    return branch, kind, capacity


def row_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return row["sucursal_num"], row["tipo"], row["capacidad"]


def has_activity(item: dict[str, Any]) -> bool:
    return any(item.get(key) not in (None, "", [], {}) for key in OPERATIONAL_KEYS)


def supplier_owned_inactive(item: dict[str, Any]) -> bool:
    return item.get("proveedor_nombre") == PROVIDER and item.get("proveedor_origen") == PROVIDER_ORIGIN and not has_activity(item)


def deterministic_id(source_sha: str, row: dict[str, Any], existing: set[str]) -> str:
    salt = 0
    while True:
        raw = f"{VERSION}|{source_sha}|{row['nro_extintor']}|{salt}".encode()
        candidate = hashlib.sha256(raw).hexdigest()[:12]
        if candidate not in existing:
            return candidate
        salt += 1


def desired_after(before: dict[str, Any], row: dict[str, Any], source_sha: str) -> dict[str, Any]:
    after = copy.deepcopy(before)
    after.update({
        "proveedor_nombre": PROVIDER,
        "proveedor_origen": PROVIDER_ORIGIN,
        "proveedor_fuente_sha256": source_sha,
        "proveedor_fila": row["row"],
        "proveedor_nro_extintor": row["nro_extintor"],
        "proveedor_tipo": row["tipo"],
        "proveedor_capacidad": row["capacidad"],
        "fecha_vencimiento_proveedor": row["fecha_vencimiento_proveedor"],
    })
    if not after.get("fecha_vencimiento_manual"):
        after["fecha_vencimiento"] = row["fecha_vencimiento_proveedor"]
    return after


def operation(kind: str, index: int | None, before: Any, after: Any) -> dict[str, Any]:
    identity = {"version": VERSION, "kind": kind, "index": index, "before": object_hash(before), "after": object_hash(after)}
    item = before or after or {}
    return {
        "operation_id": object_hash(identity), "kind": kind, "original_index": index,
        "item_id": item.get("id"), "before_sha256": object_hash(before), "after_sha256": object_hash(after),
        "before": before, "after": after,
    }


def conflict(row: dict[str, Any] | None, item: dict[str, Any] | None, reason: str) -> dict[str, Any]:
    return {
        "conflict_id": object_hash({"version": VERSION, "row": (row or {}).get("row"), "item_id": (item or {}).get("id"), "reason": reason}),
        "source_row": (row or {}).get("row"), "item_id": (item or {}).get("id"),
        "sucursal_num": (row or {}).get("sucursal_num") or (item_key(item or {}) or (None,))[0],
        "reason": reason,
    }


def make_plan(input_path: Path, xls_path: Path, expected_sha: str) -> dict[str, Any]:
    inventory, input_sha = load_inventory(input_path, expected_sha)
    source = parse_xls(xls_path)
    items = inventory["matafuegos"]
    canonical_ids: dict[str, list[tuple[int, dict[str, Any]]]] = defaultdict(list)
    supplier_ids: dict[str, list[tuple[int, dict[str, Any]]]] = defaultdict(list)
    by_key: dict[tuple[str, str, str], list[tuple[int, dict[str, Any]]]] = defaultdict(list)
    for index, item in enumerate(items):
        canonical = str(item.get("nro_extintor") or "").strip()
        if canonical:
            canonical_ids[canonical].append((index, item))
        if item.get("proveedor_nombre") == PROVIDER and item.get("proveedor_origen") == PROVIDER_ORIGIN:
            supplier = str(item.get("proveedor_nro_extintor") or "").strip()
            if supplier:
                supplier_ids[supplier].append((index, item))
        key = item_key(item)
        if key:
            by_key[key].append((index, item))
    for pool in by_key.values():
        pool.sort(key=lambda pair: str(pair[1].get("id")))

    active_rows = [
        row for row in source["rows"]
        if row["sucursal_num"] and row["sucursal_num"] not in CONFLICT_BRANCHES and not row["inactive_green"]
    ]
    inactive_green_rows = [row for row in source["rows"] if row.get("inactive_green")]
    excluded_conflicts = [row for row in source["rows"] if row["sucursal_num"] in CONFLICT_BRANCHES]
    operations: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    matched_indexes: set[int] = set()
    reserved_indexes: set[int] = set()
    unmatched_rows: list[dict[str, Any]] = []
    match_counts = Counter()

    for row in active_rows:
        identifier = row["nro_extintor"]
        matches = canonical_ids.get(identifier, [])
        match_kind = "nro_extintor"
        if not matches:
            matches = supplier_ids.get(identifier, [])
            match_kind = "proveedor_nro_extintor"
        if len(matches) > 1:
            conflicts.append(conflict(row, None, f"{match_kind} no es único en inventario; no se muta"))
            reserved_indexes.update(index for index, _ in matches)
            continue
        if len(matches) == 1:
            index, before = matches[0]
            reserved_indexes.add(index)
            if item_key(before) != row_key(row):
                conflicts.append(conflict(row, before, f"{match_kind} único pero sucursal/tipo/capacidad incompatible; no se muta"))
                continue
            matched_indexes.add(index)
            match_counts[match_kind] += 1
            after = desired_after(before, row, source["xls_sha256"])
            if object_hash(before) != object_hash(after):
                operations.append(operation("update", index, before, after))
            continue
        unmatched_rows.append(row)

    available: dict[tuple[str, str, str], list[tuple[int, dict[str, Any]]]] = defaultdict(list)
    for key, pool in by_key.items():
        available[key] = [pair for pair in pool if pair[0] not in matched_indexes and pair[0] not in reserved_indexes]
    existing_ids = {str(item.get("id")) for item in items}
    for row in unmatched_rows:
        pool = available[row_key(row)]
        if pool:
            index, before = pool.pop(0)
            matched_indexes.add(index)
            match_counts["sucursal_tipo_capacidad"] += 1
            after = desired_after(before, row, source["xls_sha256"])
            if object_hash(before) != object_hash(after):
                operations.append(operation("update", index, before, after))
        else:
            new_id = deterministic_id(source["xls_sha256"], row, existing_ids)
            existing_ids.add(new_id)
            before = None
            base = {
                "id": new_id, "sucursal": f"Sucursal {row['sucursal_num']}", "sucursal_num": row["sucursal_num"],
                "local_nombre": "", "ubicacion": "", "tipo": row["tipo"], "cantidad": 1,
                "capacidad": row["capacidad"], "fecha_carga": "", "fecha_vencimiento": "",
                "estado_manual": "", "origen": PROVIDER_ORIGIN, "nro_extintor": row["nro_extintor"],
            }
            after = desired_after(base, row, source["xls_sha256"])
            operations.append(operation("add", None, before, after))
            match_counts["alta"] += 1

    active_branches = set(source["active_branch_numbers"])
    for index, item in enumerate(items):
        key = item_key(item)
        if index in matched_indexes or index in reserved_indexes or not key or key[0] not in active_branches:
            continue
        if item.get("proveedor_nombre") != PROVIDER or item.get("proveedor_origen") != PROVIDER_ORIGIN:
            continue
        if supplier_owned_inactive(item):
            operations.append(operation("delete_safe", index, item, None))
        else:
            conflicts.append(conflict(None, item, "registro Diprogom excedente con actividad; no se elimina"))

    kinds = Counter(item["kind"] for item in operations)
    return {
        "schema": "tecman.diprogom-plan/v1", "version": VERSION, "mode": "dry-run",
        "input": str(input_path), "input_sha256": input_sha,
        "xls": str(xls_path), "xls_sha256": source["xls_sha256"],
        "safety": {"network": False, "production": False, "in_place": False, "excluded_branch_mutations": 0, "inactive_green_mutations": 0, "pending_morzat_mutations": 0},
        "source_summary": source["summary"],
        "active_branch_numbers": source["active_branch_numbers"],
        "inactive_green": {
            "branch_counts": dict(sorted(Counter(row["sucursal_num"] for row in inactive_green_rows).items())),
            "rows": len(inactive_green_rows),
            "status": "historico_inactivo_no_asignar_diprogom",
        },
        "excluded_provider_conflicts": {branch: {"rows": count, "status": "conflicto_proveedor"} for branch, count in sorted(CONFLICT_BRANCHES.items())},
        "pending": {"label": PENDING_LABEL, "address": PENDING_ADDRESS, "rows": EXPECTED_PENDING_ROWS, "status": "pendiente_sin_numero_no_inferir_garin"},
        "match_summary": dict(sorted(match_counts.items())),
        "summary": {
            "adds": kinds["add"], "updates": kinds["update"], "safe_deletes": kinds["delete_safe"],
            "conflicts": len(conflicts), "operations": len(operations), "input_total": len(items),
            "final_total": len(items) + kinds["add"] - kinds["delete_safe"],
            "automatic_scope_branches": len(source["active_branch_numbers"]), "automatic_scope_equipment": len(active_rows),
        },
        "conflicts": conflicts, "excluded_source_rows": len(excluded_conflicts) + len(inactive_green_rows) + EXPECTED_PENDING_ROWS,
        "operations": operations,
    }


def ensure_distinct(**paths: Path) -> None:
    seen: dict[Path, str] = {}
    for label, path in paths.items():
        resolved = path.resolve()
        if resolved in seen:
            raise ValueError(f"rutas deben ser distintas: {seen[resolved]} y {label}")
        seen[resolved] = label


def apply_plan(input_path: Path, expected_sha: str, plan_path: Path, output: Path, journal: Path) -> dict[str, Any]:
    ensure_distinct(input=input_path, plan=plan_path, output=output, journal=journal)
    inventory, actual = load_inventory(input_path, expected_sha)
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if plan.get("input_sha256") != actual or plan.get("schema") != "tecman.diprogom-plan/v1":
        raise ValueError("plan no corresponde al input o esquema esperado")
    items = copy.deepcopy(inventory["matafuegos"])
    indexes = {str(item.get("id")): index for index, item in enumerate(items)}
    deletes: set[str] = set()
    for row in plan.get("operations", []):
        kind, item_id = row.get("kind"), str(row.get("item_id"))
        if kind == "add":
            if item_id in indexes or object_hash(row.get("after")) != row.get("after_sha256"):
                raise ValueError(f"alta inválida o existente: {item_id}")
            indexes[item_id] = len(items)
            items.append(copy.deepcopy(row["after"]))
        elif kind in {"update", "delete_safe"}:
            if item_id not in indexes or object_hash(items[indexes[item_id]]) != row.get("before_sha256"):
                raise ValueError(f"before divergente: {item_id}")
            if kind == "update":
                if object_hash(row.get("after")) != row.get("after_sha256"):
                    raise ValueError(f"after divergente: {item_id}")
                items[indexes[item_id]] = copy.deepcopy(row["after"])
            else:
                deletes.add(item_id)
        else:
            raise ValueError(f"operación no permitida: {kind}")
    items = [item for item in items if str(item.get("id")) not in deletes]
    result = copy.deepcopy(inventory)
    result["matafuegos"] = items
    guards = {"before": object_hash(inventory), "after": object_hash(result), "before_count": len(inventory["matafuegos"]), "after_count": len(items)}
    journal_rows = copy.deepcopy(plan["operations"])
    journal_document = {
        "schema": "tecman.diprogom-journal/v2",
        "guards": guards,
        "before_file_sha256": actual,
        "before_file_base64": base64.b64encode(input_path.read_bytes()).decode("ascii"),
        "operations": journal_rows,
    }
    atomic_json(output, result)
    atomic_json(journal, journal_document)
    return {"applied": len(journal_rows), "output_sha256": sha256_file(output), "journal": str(journal)}


def rollback(input_path: Path, expected_sha: str, journal: Path, output: Path) -> dict[str, Any]:
    ensure_distinct(input=input_path, journal=journal, output=output)
    inventory, _ = load_inventory(input_path, expected_sha)
    journal_document = json.loads(journal.read_text(encoding="utf-8"))
    if isinstance(journal_document, dict) and journal_document.get("schema") == "tecman.diprogom-journal/v2":
        rows = journal_document.get("operations", [])
        guards = journal_document.get("guards")
        original_bytes = base64.b64decode(journal_document.get("before_file_base64", ""), validate=True)
        if hashlib.sha256(original_bytes).hexdigest() != journal_document.get("before_file_sha256"):
            raise ValueError("respaldo original del journal divergente")
    else:
        rows = journal_document
        guards = rows[0].get("journal_guards") if rows else None
        original_bytes = None
    if not rows:
        raise ValueError("journal vacío")
    if not isinstance(guards, dict) or object_hash(inventory) != guards.get("after"):
        raise ValueError("precondición after global falló")
    items = copy.deepcopy(inventory["matafuegos"])
    for row in reversed([entry for entry in rows if entry["kind"] == "add"]):
        index = next((i for i, item in enumerate(items) if str(item.get("id")) == str(row.get("item_id"))), None)
        if index is None or object_hash(items[index]) != row["after_sha256"]:
            raise ValueError("alta divergente")
        items.pop(index)
    for row in [entry for entry in rows if entry["kind"] == "update"]:
        index = next((i for i, item in enumerate(items) if str(item.get("id")) == str(row.get("item_id"))), None)
        if index is None or object_hash(items[index]) != row["after_sha256"]:
            raise ValueError("update divergente")
        items[index] = copy.deepcopy(row["before"])
    for row in sorted((entry for entry in rows if entry["kind"] == "delete_safe"), key=lambda entry: entry["original_index"]):
        if any(str(item.get("id")) == str(row.get("item_id")) for item in items):
            raise ValueError("baja reapareció")
        items.insert(row["original_index"], copy.deepcopy(row["before"]))
    result = copy.deepcopy(inventory)
    result["matafuegos"] = items
    if object_hash(result) != guards.get("before"):
        raise ValueError("rollback no reconstruyó exactamente el input")
    if original_bytes is not None:
        if json.loads(original_bytes.decode("utf-8")) != result:
            raise ValueError("respaldo original no coincide con rollback reconstruido")
        atomic_bytes(output, original_bytes)
    else:
        atomic_json(output, result)
    output_sha = sha256_file(output)
    if original_bytes is not None and output_sha != journal_document["before_file_sha256"]:
        raise ValueError("rollback no restauró los bytes exactos")
    return {"rolled_back": len(rows), "output_sha256": output_sha}


def sanitized_report(plan: dict[str, Any]) -> dict[str, Any]:
    keys = ("schema", "version", "mode", "input_sha256", "xls_sha256", "safety", "source_summary", "active_branch_numbers", "inactive_green", "excluded_provider_conflicts", "pending", "match_summary", "summary", "conflicts")
    return {key: copy.deepcopy(plan[key]) for key in keys}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--xls", type=Path)
    parser.add_argument("--plan-output", type=Path)
    parser.add_argument("--report-output", type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--rollback", action="store_true")
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--journal", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        if args.apply:
            if not all((args.plan, args.journal, args.output)):
                parser.error("--apply requiere --plan --journal --output")
            result = apply_plan(args.input, args.expected_sha256, args.plan, args.output, args.journal)
        elif args.rollback:
            if not all((args.journal, args.output)):
                parser.error("--rollback requiere --journal --output")
            result = rollback(args.input, args.expected_sha256, args.journal, args.output)
        else:
            if not all((args.xls, args.plan_output)):
                parser.error("dry-run requiere --xls --plan-output")
            ensure_distinct(input=args.input, xls=args.xls, plan=args.plan_output, **({"report": args.report_output} if args.report_output else {}))
            plan = make_plan(args.input, args.xls, args.expected_sha256)
            atomic_json(args.plan_output, plan)
            if args.report_output:
                atomic_json(args.report_output, sanitized_report(plan))
            result = {"plan": str(args.plan_output), "report": str(args.report_output) if args.report_output else None, "summary": plan["summary"], "source_summary": plan["source_summary"]}
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    except (OSError, ValueError, json.JSONDecodeError, xlrd.XLRDError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
