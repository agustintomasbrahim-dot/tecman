#!/usr/bin/env python3
"""Conciliación local Diprogom -> Fuego Cero con plan, journal y rollback.

No usa red ni escribe sobre inputs. Dry-run es el modo predeterminado.
"""
from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import importlib.util
import json
import os
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
VERSION = "inventarios-tecman-2026-09-28-v1"
EXPECTED_BASE_COUNT = 1254
EXPECTED_DIPROGOM_BRANCHES = 25
EXPECTED_FUEGO_BRANCHES = 35


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"no se pudo cargar {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


diprogom = load_module("tecman_import_diprogom", ROOT / "scripts/import_diprogom.py")
fuego = load_module("tecman_import_fuego", ROOT / "scripts/import_fuego_cero.py")


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


def ensure_distinct(**paths: Path) -> None:
    seen: dict[Path, str] = {}
    for label, path in paths.items():
        resolved = path.resolve()
        if resolved in seen:
            raise ValueError(f"rutas deben ser distintas: {seen[resolved]} y {label}")
        seen[resolved] = label


def verify_hash(path: Path, expected: str, label: str) -> str:
    actual = sha256_file(path)
    if actual != expected.lower():
        raise ValueError(f"SHA {label} inesperado: esperado {expected.lower()}, actual {actual}")
    return actual


def normalize_child_plan(plan: dict[str, Any], input_label: str, source_key: str, source_label: str) -> dict[str, Any]:
    normalized = copy.deepcopy(plan)
    normalized["input"] = input_label
    normalized[source_key] = source_label
    return normalized


def inventory_stats(document: dict[str, Any]) -> dict[str, Any]:
    items = document["matafuegos"]
    ids = Counter(str(item.get("id")) for item in items)
    supplier_ids: dict[tuple[str, str], list[str]] = defaultdict(list)
    for item in items:
        provider = str(item.get("proveedor_nombre") or "").strip()
        supplier_id = str(item.get("proveedor_nro_extintor") or "").strip()
        if provider and supplier_id:
            supplier_ids[(provider, supplier_id)].append(str(item.get("id")))
    duplicate_supplier_ids = [
        {"proveedor": provider, "proveedor_id": supplier_id, "ids": sorted(item_ids)}
        for (provider, supplier_id), item_ids in sorted(supplier_ids.items())
        if len(item_ids) > 1
    ]
    return {
        "total": len(items),
        "duplicate_ids": sorted(item_id for item_id, count in ids.items() if count > 1),
        "duplicate_supplier_ids": duplicate_supplier_ids,
    }


def _materialize(plan: dict[str, Any], input_path: Path, output_path: Path, workspace: Path) -> None:
    dip_plan_path = workspace / "dip-plan.json"
    dip_output = workspace / "dip-output.json"
    dip_journal = workspace / "dip-journal.json"
    fuego_plan_path = workspace / "fuego-plan.json"
    fuego_journal = workspace / "fuego-journal.json"
    atomic_json(dip_plan_path, plan["stages"]["diprogom"])
    diprogom.apply_plan(input_path, plan["input_sha256"], dip_plan_path, dip_output, dip_journal)
    atomic_json(fuego_plan_path, plan["stages"]["fuego_cero"])
    fuego.apply_plan(dip_output, sha256_file(dip_output), fuego_plan_path, output_path, fuego_journal)


def make_plan(input_path: Path, input_sha: str, dip_source: Path, dip_sha: str,
              fuego_source: Path, fuego_sha: str) -> tuple[dict[str, Any], dict[str, Any]]:
    verify_hash(input_path, input_sha, "input")
    verify_hash(dip_source, dip_sha, "fuente Diprogom")
    verify_hash(fuego_source, fuego_sha, "fuente Fuego Cero")
    inventory, _ = diprogom.load_inventory(input_path, input_sha)
    input_count = len(inventory["matafuegos"])

    dip_plan = diprogom.make_plan(input_path, dip_source, input_sha)
    dip_branches = set(dip_plan["active_branch_numbers"])
    if len(dip_branches) != EXPECTED_DIPROGOM_BRANCHES:
        raise ValueError(f"invariante rota: Diprogom debe tener {EXPECTED_DIPROGOM_BRANCHES} sucursales activas")

    with tempfile.TemporaryDirectory(prefix="tecman-inventarios-plan-") as directory:
        work = Path(directory)
        dip_plan_path = work / "dip-plan.json"
        dip_output = work / "dip-output.json"
        dip_journal = work / "dip-journal.json"
        atomic_json(dip_plan_path, dip_plan)
        diprogom.apply_plan(input_path, input_sha, dip_plan_path, dip_output, dip_journal)
        dip_output_sha = sha256_file(dip_output)
        fuego_plan = fuego.make_plan(dip_output, fuego_source, dip_output_sha)
        fuego_branches = set(fuego_plan["confirmed_branch_numbers"])
        if len(fuego_branches) != EXPECTED_FUEGO_BRANCHES:
            raise ValueError(f"invariante rota: Fuego Cero debe tener {EXPECTED_FUEGO_BRANCHES} sucursales confirmadas")
        overlap = sorted(dip_branches & fuego_branches)
        if overlap:
            raise ValueError(f"invariante rota: intersección Diprogom/Fuego Cero no vacía: {overlap}")

        fuego_plan_path = work / "fuego-plan.json"
        final_output = work / "final.json"
        fuego_journal = work / "fuego-journal.json"
        atomic_json(fuego_plan_path, fuego_plan)
        fuego.apply_plan(dip_output, dip_output_sha, fuego_plan_path, final_output, fuego_journal)
        final_document = json.loads(final_output.read_text(encoding="utf-8"))

    dip_ids = {str(op["item_id"]) for op in dip_plan["operations"]}
    fuego_ids = {str(op["item_id"]) for op in fuego_plan["operations"]}
    interactions = sorted(dip_ids & fuego_ids)
    stats = inventory_stats(final_document)
    if stats["duplicate_ids"]:
        raise ValueError(f"IDs duplicados en salida: {stats['duplicate_ids']}")

    normalized_dip = normalize_child_plan(dip_plan, "base", "xls", "diprogom-source")
    normalized_fuego = normalize_child_plan(fuego_plan, "diprogom-output", "xlsx", "fuego-cero-source")
    plan = {
        "schema": "tecman.inventarios-unificados-plan/v1",
        "version": VERSION,
        "mode": "dry-run",
        "input_sha256": input_sha.lower(),
        "source_sha256": {"diprogom": dip_sha.lower(), "fuego_cero": fuego_sha.lower()},
        "safety": {"network": False, "production": False, "in_place": False, "stage_order": ["diprogom", "fuego_cero"]},
        "invariants": {
            "base_count": input_count,
            "diprogom_active_branch_count": len(dip_branches),
            "fuego_confirmed_branch_count": len(fuego_branches),
            "branch_intersection": overlap,
        },
        "stages": {"diprogom": normalized_dip, "fuego_cero": normalized_fuego},
        "summary": {
            "input_total": input_count,
            "diprogom": dip_plan["summary"],
            "after_diprogom_total": dip_plan["summary"]["final_total"],
            "fuego_cero": fuego_plan["summary"],
            "final_total": stats["total"],
            "cross_stage_item_ids": interactions,
            "duplicate_ids": stats["duplicate_ids"],
            "duplicate_supplier_ids": stats["duplicate_supplier_ids"],
            "combined_operations": dip_plan["summary"]["operations"] + fuego_plan["summary"]["operations"],
            "combined_conflicts": dip_plan["summary"]["conflicts"] + fuego_plan["summary"]["conflicts"],
        },
    }
    manifest = {
        "schema": "tecman.inventarios-unificados-manifest/v1",
        "version": VERSION,
        "input_sha256": plan["input_sha256"],
        "source_sha256": plan["source_sha256"],
        "safety": plan["safety"],
        "invariants": plan["invariants"],
        "summary": plan["summary"],
        "conflicts": {
            "diprogom": dip_plan["conflicts"],
            "fuego_cero": fuego_plan["conflicts"],
        },
    }
    return plan, manifest


def apply_plan(input_path: Path, input_sha: str, dip_source: Path, dip_sha: str,
               fuego_source: Path, fuego_sha: str, plan_path: Path, plan_sha: str,
               output: Path, journal: Path, manifest_output: Path) -> dict[str, Any]:
    ensure_distinct(input=input_path, dip_source=dip_source, fuego_source=fuego_source,
                    plan=plan_path, output=output, journal=journal, manifest=manifest_output)
    verify_hash(input_path, input_sha, "input")
    verify_hash(dip_source, dip_sha, "fuente Diprogom")
    verify_hash(fuego_source, fuego_sha, "fuente Fuego Cero")
    verify_hash(plan_path, plan_sha, "plan")
    stored = json.loads(plan_path.read_text(encoding="utf-8"))
    regenerated, manifest = make_plan(input_path, input_sha, dip_source, dip_sha, fuego_source, fuego_sha)
    if object_hash(stored) != object_hash(regenerated):
        raise ValueError("plan divergente respecto de input/fuentes actuales")
    with tempfile.TemporaryDirectory(prefix="tecman-inventarios-apply-") as directory:
        temporary_output = Path(directory) / "final.json"
        _materialize(stored, input_path, temporary_output, Path(directory))
        result_bytes = temporary_output.read_bytes()
        final_document = json.loads(result_bytes.decode("utf-8"))
    final_canonical_sha = object_hash(final_document)
    journal_document = {
        "schema": "tecman.inventarios-unificados-journal/v1",
        "version": VERSION,
        "plan_sha256": plan_sha.lower(),
        "before_file_sha256": input_sha.lower(),
        "before_canonical_sha256": object_hash(json.loads(input_path.read_text(encoding="utf-8"))),
        "after_file_sha256": hashlib.sha256(result_bytes).hexdigest(),
        "after_canonical_sha256": final_canonical_sha,
        "before_file_base64": base64.b64encode(input_path.read_bytes()).decode("ascii"),
        "summary": stored["summary"],
    }
    atomic_bytes(output, result_bytes)
    atomic_json(journal, journal_document)
    manifest = dict(manifest, plan_sha256=plan_sha.lower(), output_sha256=sha256_file(output), output_canonical_sha256=final_canonical_sha)
    atomic_json(manifest_output, manifest)
    return {"applied": stored["summary"]["combined_operations"], "output_sha256": sha256_file(output), "journal": str(journal), "manifest": str(manifest_output)}


def rollback(input_path: Path, input_sha: str, journal_path: Path, output: Path) -> dict[str, Any]:
    ensure_distinct(input=input_path, journal=journal_path, output=output)
    verify_hash(input_path, input_sha, "salida aplicada")
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    if journal.get("schema") != "tecman.inventarios-unificados-journal/v1":
        raise ValueError("journal incompatible")
    current = json.loads(input_path.read_text(encoding="utf-8"))
    if object_hash(current) != journal.get("after_canonical_sha256"):
        raise ValueError("salida aplicada diverge del journal")
    original = base64.b64decode(journal.get("before_file_base64", ""), validate=True)
    if hashlib.sha256(original).hexdigest() != journal.get("before_file_sha256"):
        raise ValueError("backup original corrupto")
    if object_hash(json.loads(original.decode("utf-8"))) != journal.get("before_canonical_sha256"):
        raise ValueError("backup original canónico corrupto")
    atomic_bytes(output, original)
    return {"rolled_back": journal["summary"]["combined_operations"], "output_sha256": sha256_file(output), "byte_exact": True}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--expected-input-sha256", required=True)
    parser.add_argument("--diprogom-source", type=Path)
    parser.add_argument("--expected-diprogom-sha256")
    parser.add_argument("--fuego-source", type=Path)
    parser.add_argument("--expected-fuego-sha256")
    parser.add_argument("--plan-output", type=Path)
    parser.add_argument("--manifest-output", type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--rollback", action="store_true")
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--expected-plan-sha256")
    parser.add_argument("--journal", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        if args.rollback:
            if not all((args.journal, args.output)):
                parser.error("--rollback requiere --journal --output")
            result = rollback(args.input, args.expected_input_sha256, args.journal, args.output)
        elif args.apply:
            if not all((args.diprogom_source, args.expected_diprogom_sha256, args.fuego_source,
                        args.expected_fuego_sha256, args.plan, args.expected_plan_sha256,
                        args.output, args.journal, args.manifest_output)):
                parser.error("--apply requiere fuentes/hashes, --plan/hash, --output, --journal y --manifest-output")
            result = apply_plan(args.input, args.expected_input_sha256, args.diprogom_source,
                                args.expected_diprogom_sha256, args.fuego_source,
                                args.expected_fuego_sha256, args.plan, args.expected_plan_sha256,
                                args.output, args.journal, args.manifest_output)
        else:
            if not all((args.diprogom_source, args.expected_diprogom_sha256, args.fuego_source,
                        args.expected_fuego_sha256, args.plan_output, args.manifest_output)):
                parser.error("dry-run requiere fuentes/hashes, --plan-output y --manifest-output")
            ensure_distinct(input=args.input, diprogom_source=args.diprogom_source,
                            fuego_source=args.fuego_source, plan=args.plan_output,
                            manifest=args.manifest_output)
            plan, manifest = make_plan(args.input, args.expected_input_sha256,
                                       args.diprogom_source, args.expected_diprogom_sha256,
                                       args.fuego_source, args.expected_fuego_sha256)
            atomic_json(args.plan_output, plan)
            manifest["plan_sha256"] = sha256_file(args.plan_output)
            atomic_json(args.manifest_output, manifest)
            result = {"plan": str(args.plan_output), "plan_sha256": sha256_file(args.plan_output),
                      "manifest": str(args.manifest_output), "summary": plan["summary"]}
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=__import__("sys").stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
