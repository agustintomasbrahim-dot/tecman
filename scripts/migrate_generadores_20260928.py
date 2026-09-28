#!/usr/bin/env python3
"""Migra explícitamente la captura de generadores 2026-09-28 sobre un JSON local.

Nunca se ejecuta al importar o arrancar la aplicación. Dry-run es el modo default.
"""
from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import json
import os
import re
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

VERSION = "generadores-captura-2026-09-28-v1"
CAPTURE_SHA256 = "d11c399b7881eb551938523f673dfaf531842e9c1dcbacaa74fca1234d437753"
SOURCE_NAME = "captura_inventario_grupos_2026-09-28"
REVISION = "2026-09-28"
REVISION_AT = "2026-09-28T00:00:00"
EXPECTED_ROWS = 21
AUTHORITATIVE_FIELDS = {
    "marca", "modelo", "numero_serie", "combustible", "ubicacion", "estado_equipo",
    "ultima_revision", "proximo_mantenimiento", "proveedor", "observaciones",
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
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        try: os.unlink(temporary)
        except FileNotFoundError: pass
        raise


def atomic_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(value); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        try: os.unlink(temporary)
        except FileNotFoundError: pass
        raise


def ensure_distinct(**paths: Path) -> None:
    seen = {}
    for label, path in paths.items():
        resolved = path.resolve()
        if resolved in seen: raise ValueError(f"rutas deben ser distintas: {seen[resolved]} y {label}")
        seen[resolved] = label


def verify_hash(path: Path, expected: str, label: str) -> str:
    actual = sha256_file(path)
    if actual != expected.lower():
        raise ValueError(f"SHA {label} inesperado: esperado {expected.lower()}, actual {actual}")
    return actual


def branch_num(value: Any) -> str:
    match = re.search(r"(\d{1,3})", str(value or ""))
    if not match: raise ValueError(f"sucursal inválida: {value!r}")
    return f"{int(match.group(1)):03d}"


def load_input(path: Path, expected_sha: str) -> tuple[dict[str, Any], str]:
    actual = verify_hash(path, expected_sha, "input")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("grupos_electrogenos"), list):
        raise ValueError("input debe contener grupos_electrogenos[]")
    ids = [str(item.get("id")) for item in data["grupos_electrogenos"]]
    if len(ids) != len(set(ids)): raise ValueError("IDs duplicados en input")
    return data, actual


def load_source(path: Path, expected_sha: str) -> tuple[dict[str, Any], str]:
    actual = verify_hash(path, expected_sha, "fuente")
    source = json.loads(path.read_text(encoding="utf-8"))
    if source.get("schema") != "tecman.generadores-captura/v1" or source.get("revision") != REVISION:
        raise ValueError("fuente incompatible")
    if source.get("capture_sha256") != CAPTURE_SHA256:
        raise ValueError("hash de captura declarado inesperado")
    rows = source.get("rows")
    if not isinstance(rows, list) or len(rows) != EXPECTED_ROWS:
        raise ValueError(f"la fuente debe tener {EXPECTED_ROWS} filas")
    branches = [branch_num(row.get("sucursal")) for row in rows]
    if len(set(branches)) != EXPECTED_ROWS:
        raise ValueError("sucursales duplicadas en fuente")
    return source, actual


def new_item(row: dict[str, Any], branch: str) -> dict[str, Any]:
    item = {
        "id": f"ge-20260928-{branch}", "sucursal": f"Sucursal {branch}", "sucursal_num": branch,
        "marca": "", "modelo": "", "numero_serie": "", "potencia": "", "combustible": "",
        "ubicacion": "", "estado_equipo": "", "ultima_revision": "", "proximo_mantenimiento": "",
        "proveedor": "", "observaciones": "", "estado_validacion": "pendiente_validacion",
        "diferencias": "", "notificacion_sucursal_pendiente": True, "novedades": [], "historial": [],
        "created_at": REVISION_AT,
    }
    for field in AUTHORITATIVE_FIELDS & row.keys(): item[field] = str(row.get(field) or "").strip()
    return item


def desired(before: dict[str, Any], row: dict[str, Any], branch: str) -> dict[str, Any]:
    after = copy.deepcopy(before)
    after["sucursal"] = f"Sucursal {branch}"; after["sucursal_num"] = branch
    for field in AUTHORITATIVE_FIELDS & row.keys(): after[field] = str(row.get(field) or "").strip()
    after.update({"fuente_importacion": SOURCE_NAME, "fuente_revision": REVISION, "fuente_sha256": CAPTURE_SHA256})
    return after


def operation(kind: str, index: int | None, before: Any, after: Any) -> dict[str, Any]:
    identity = {"version": VERSION, "kind": kind, "index": index, "before": object_hash(before), "after": object_hash(after)}
    item = before or after or {}
    return {"operation_id": object_hash(identity), "kind": kind, "original_index": index,
            "item_id": item.get("id"), "before_sha256": object_hash(before), "after_sha256": object_hash(after),
            "before": before, "after": after}


def make_plan(input_path: Path, input_sha: str, source_path: Path, source_sha: str) -> dict[str, Any]:
    inventory, actual_input = load_input(input_path, input_sha)
    source, actual_source = load_source(source_path, source_sha)
    items = inventory["grupos_electrogenos"]
    by_branch: dict[str, list[tuple[int, dict[str, Any]]]] = defaultdict(list)
    for index, item in enumerate(items):
        try: by_branch[branch_num(item.get("sucursal_num") or item.get("sucursal"))].append((index, item))
        except ValueError: pass
    operations, conflicts = [], []
    existing_ids = {str(item.get("id")) for item in items}
    for row in source["rows"]:
        branch = branch_num(row["sucursal"])
        matches = by_branch.get(branch, [])
        imported = [pair for pair in matches if str(pair[1].get("fuente_importacion", "")).startswith(("inventario_grupos_", "captura_inventario_grupos_")) or str(pair[1].get("id", "")) in {f"ge-20260923-{branch}", f"ge-20260928-{branch}"}]
        candidates = imported or matches
        if len(candidates) > 1:
            conflicts.append({"sucursal_num": branch, "ids": sorted(str(item.get("id")) for _, item in candidates), "reason": "más de un candidato; no se muta"})
            continue
        if candidates:
            index, before = candidates[0]
        else:
            index, before = None, new_item(row, branch)
            if before["id"] in existing_ids: raise ValueError(f"ID determinístico ya existe: {before['id']}")
            existing_ids.add(before["id"])
        after = desired(before, row, branch)
        if object_hash(before) != object_hash(after):
            action = "inventario_autoritativo_importado" if index is None else "inventario_autoritativo_actualizado"
            changed = {field: {"before": before.get(field), "after": after.get(field)} for field in sorted(set(before) | set(after)) if before.get(field) != after.get(field)}
            after["updated_at"] = REVISION_AT
            history = copy.deepcopy(after.get("historial") or [])
            history.append({"fecha": REVISION_AT, "accion": action, "actor": "Sistema", "detalle": json.dumps({"revision": REVISION, "sha256": CAPTURE_SHA256, "changes": changed}, ensure_ascii=False, sort_keys=True)})
            after["historial"] = history
            operations.append(operation("add" if index is None else "update", index, None if index is None else before, after))
    kinds = Counter(op["kind"] for op in operations)
    return {
        "schema": "tecman.generadores-plan/v1", "version": VERSION, "mode": "dry-run",
        "input": str(input_path), "input_sha256": actual_input, "source": str(source_path), "source_sha256": actual_source,
        "capture_sha256": CAPTURE_SHA256,
        "safety": {"network": False, "production": False, "in_place": False, "auto_start": False, "deletions_allowed": False},
        "summary": {"input_total": len(items), "source_rows": EXPECTED_ROWS, "adds": kinds["add"], "updates": kinds["update"],
                    "deletes": 0, "conflicts": len(conflicts), "operations": len(operations), "final_total": len(items) + kinds["add"]},
        "conflicts": conflicts, "operations": operations,
    }


def apply_plan(input_path: Path, input_sha: str, source_path: Path, source_sha: str,
               plan_path: Path, plan_sha: str, output: Path, journal: Path) -> dict[str, Any]:
    ensure_distinct(input=input_path, source=source_path, plan=plan_path, output=output, journal=journal)
    inventory, _ = load_input(input_path, input_sha); load_source(source_path, source_sha); verify_hash(plan_path, plan_sha, "plan")
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if plan.get("schema") != "tecman.generadores-plan/v1" or plan.get("input_sha256") != input_sha.lower() or plan.get("source_sha256") != source_sha.lower():
        raise ValueError("plan no corresponde a input/fuente")
    regenerated = make_plan(input_path, input_sha, source_path, source_sha)
    if object_hash(plan) != object_hash(regenerated): raise ValueError("plan divergente")
    items = copy.deepcopy(inventory["grupos_electrogenos"]); indexes = {str(item.get("id")): i for i, item in enumerate(items)}
    for op in plan["operations"]:
        item_id = str(op["item_id"])
        if op["kind"] == "add":
            if item_id in indexes or object_hash(op["after"]) != op["after_sha256"]: raise ValueError(f"alta inválida: {item_id}")
            indexes[item_id] = len(items); items.append(copy.deepcopy(op["after"]))
        elif op["kind"] == "update":
            if item_id not in indexes or object_hash(items[indexes[item_id]]) != op["before_sha256"]: raise ValueError(f"before divergente: {item_id}")
            items[indexes[item_id]] = copy.deepcopy(op["after"])
        else: raise ValueError(f"operación no permitida: {op['kind']}")
    result = copy.deepcopy(inventory); result["grupos_electrogenos"] = items
    result_bytes = json.dumps(result, ensure_ascii=False, indent=2).encode() + b"\n"
    journal_doc = {"schema": "tecman.generadores-journal/v1", "plan_sha256": plan_sha.lower(),
                   "before_file_sha256": input_sha.lower(), "before_canonical_sha256": object_hash(inventory),
                   "after_file_sha256": hashlib.sha256(result_bytes).hexdigest(), "after_canonical_sha256": object_hash(result),
                   "before_file_base64": base64.b64encode(input_path.read_bytes()).decode("ascii"), "summary": plan["summary"]}
    atomic_bytes(output, result_bytes); atomic_json(journal, journal_doc)
    return {"applied": len(plan["operations"]), "output_sha256": sha256_file(output), "journal": str(journal)}


def rollback(input_path: Path, input_sha: str, journal_path: Path, output: Path) -> dict[str, Any]:
    ensure_distinct(input=input_path, journal=journal_path, output=output)
    inventory, _ = load_input(input_path, input_sha)
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    if journal.get("schema") != "tecman.generadores-journal/v1" or object_hash(inventory) != journal.get("after_canonical_sha256"):
        raise ValueError("salida aplicada diverge del journal")
    original = base64.b64decode(journal.get("before_file_base64", ""), validate=True)
    if hashlib.sha256(original).hexdigest() != journal.get("before_file_sha256"): raise ValueError("backup original corrupto")
    atomic_bytes(output, original)
    return {"rolled_back": journal["summary"]["operations"], "output_sha256": sha256_file(output), "byte_exact": True}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True); parser.add_argument("--expected-input-sha256", required=True)
    parser.add_argument("--source", type=Path); parser.add_argument("--expected-source-sha256")
    parser.add_argument("--plan-output", type=Path); parser.add_argument("--manifest-output", type=Path)
    mode = parser.add_mutually_exclusive_group(); mode.add_argument("--apply", action="store_true"); mode.add_argument("--rollback", action="store_true")
    parser.add_argument("--plan", type=Path); parser.add_argument("--expected-plan-sha256"); parser.add_argument("--journal", type=Path); parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        if args.rollback:
            if not all((args.journal, args.output)): parser.error("--rollback requiere --journal --output")
            result = rollback(args.input, args.expected_input_sha256, args.journal, args.output)
        elif args.apply:
            if not all((args.source, args.expected_source_sha256, args.plan, args.expected_plan_sha256, args.journal, args.output)):
                parser.error("--apply requiere fuente/hash, plan/hash, journal y output")
            result = apply_plan(args.input, args.expected_input_sha256, args.source, args.expected_source_sha256, args.plan, args.expected_plan_sha256, args.output, args.journal)
        else:
            if not all((args.source, args.expected_source_sha256, args.plan_output, args.manifest_output)):
                parser.error("dry-run requiere fuente/hash, plan-output y manifest-output")
            ensure_distinct(input=args.input, source=args.source, plan=args.plan_output, manifest=args.manifest_output)
            plan = make_plan(args.input, args.expected_input_sha256, args.source, args.expected_source_sha256)
            atomic_json(args.plan_output, plan)
            manifest = {key: copy.deepcopy(plan[key]) for key in ("schema", "version", "input_sha256", "source_sha256", "capture_sha256", "safety", "summary", "conflicts")}
            manifest["plan_sha256"] = sha256_file(args.plan_output); atomic_json(args.manifest_output, manifest)
            result = {"plan": str(args.plan_output), "plan_sha256": manifest["plan_sha256"], "manifest": str(args.manifest_output), "summary": plan["summary"]}
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=__import__("sys").stderr); raise SystemExit(2)


if __name__ == "__main__": main()
