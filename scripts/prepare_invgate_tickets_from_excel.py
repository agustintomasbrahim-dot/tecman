#!/usr/bin/env python3
"""Prepare a reviewed Tecman migration draft from an InvGate workbook.

Headers are resolved only by normalized equality against explicit aliases. The
script only creates a local draft and never mutates Tecman data or calls a
remote endpoint. Use ``reconcile_invgate_migration.py`` for guarded correction.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from openpyxl import load_workbook


CLOSED_STATES = {"cerrado", "cerrar juli", "cancelado", "rechazado"}
MAX_SCAN_ROWS = 10_000
DETERMINISTIC_FALLBACK_DATE = "1970-01-01T00:00:00"
HEADER_ALIASES = {
    "sucursal": {"sucursal"},
    "estado": {"estado"},
    "prioridad": {"prioridad"},
    "fecha_solicitud": {"fecha de solicitud"},
    "fecha_realizacion": {"fecha de realizacion", "fecha de consulta"},
    "demora_ticket": {"demora de ticket"},
    "provincia": {"provincia"},
    "nro_ticket": {"nro de ticket", "numero de ticket"},
    "solicitud": {"solicitud"},
    "materiales": {"materiales", "mj:rateriales", "rateriales"},
    "ubicacion_materiales": {"ubicacion de materiales"},
}
METADATA_PREFIXES = ("proveedor", "celu", "sucursales")


def clean(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).replace("\xa0", " ").split()).strip()


def normalized(value: Any) -> str:
    text = unicodedata.normalize("NFKD", clean(value).casefold())
    return " ".join("".join(ch for ch in text if not unicodedata.combining(ch)).split())


def parsed_iso_date(value: Any) -> str:
    """Return ISO only for actual/recognized dates; never return arbitrary text."""
    if value is None or value == "":
        return ""
    if isinstance(value, dt.datetime):
        return value.isoformat()
    if isinstance(value, dt.date):
        return dt.datetime.combine(value, dt.time()).isoformat()
    text = clean(value)
    for fmt in ("%m/%d/%Y", "%d/%m/%Y", "%d-%m-%Y", "%d-%b-%Y", "%d-%B-%Y"):
        try:
            return dt.datetime.strptime(text, fmt).isoformat()
        except ValueError:
            pass
    return ""


# Backwards-compatible name used by callers; semantics are now deliberately strict.
iso_date = parsed_iso_date


def norm_sucursal(value: Any) -> tuple[str, str]:
    text = clean(value)
    if not text:
        return "", ""
    if isinstance(value, int):
        return f"Sucursal {value:03d}", f"{value:03d}"
    if isinstance(value, float) and value.is_integer():
        number = int(value)
        return f"Sucursal {number:03d}", f"{number:03d}"
    match = re.fullmatch(r"0*(\d{1,3})", text)
    if match:
        code = f"{int(match.group(1)):03d}"
        return f"Sucursal {code}", code
    return text, ""


def is_numeric_ticket(value: Any) -> bool:
    if isinstance(value, int):
        return True
    if isinstance(value, float):
        return value.is_integer()
    return bool(re.fullmatch(r"\d+(?:\.0+)?", clean(value)))


def find_header(rows: list[tuple[Any, ...]]) -> int | None:
    for i, row in enumerate(rows[:25]):
        values = {normalized(cell) for cell in row[:25] if clean(cell)}
        if "sucursal" in values and ("solicitud" in values or "nro de ticket" in values):
            return i
    return None


def resolve_columns(headers: Iterable[Any]) -> dict[str, int]:
    """Resolve by normalized equality; ambiguous duplicate aliases are rejected."""
    normalized_headers = [normalized(value) for value in headers]
    resolved: dict[str, int] = {}
    for field, aliases in HEADER_ALIASES.items():
        matches = [i for i, header in enumerate(normalized_headers) if header in aliases]
        if len(matches) > 1:
            raise ValueError(f"encabezado ambiguo para {field}: columnas {matches}")
        if matches:
            resolved[field] = matches[0]
    for required in ("sucursal", "solicitud", "nro_ticket"):
        if required not in resolved:
            raise ValueError(f"falta encabezado requerido: {required}")
    return resolved


def column_index(headers: list[str], *needles: str) -> int | None:
    """Compatibility helper using equality, never substring matching."""
    aliases = {normalized(needle) for needle in needles}
    matches = [i for i, header in enumerate(headers) if normalized(header) in aliases]
    if len(matches) > 1:
        raise ValueError(f"encabezado ambiguo: {needles}")
    return matches[0] if matches else None


def classify(sheet: str, description: str) -> tuple[str, str]:
    text = f"{sheet} {description}".lower()
    if any(word in text for word in ("aire", "aa ", "a.a", "split", "freon", "frio", "calor")):
        return "Aire Acondicionado", "Reparación"
    if any(word in text for word in ("luminaria", "luz", "luces", "tablero", "termica", "cable")):
        return "Problema Eléctrico", "Luminarias"
    if any(word in text for word in ("filtr", "gotera", "membrana", "techo")):
        return "Filtraciones", "Por lluvia"
    if any(word in text for word in ("pint", "durlock")):
        return "Pintura", "Interior"
    if any(word in text for word in ("material", "tubo led", "garrafa")):
        return "Materiales", "Solicitud de materiales"
    if any(word in text for word in ("persiana", "cortina", "ascensor", "escalera", "vidrio", "puerta")):
        return "Reparaciones", "General"
    return "Otro", "Otro"


def map_estado(value: str) -> str:
    state = clean(value)
    low = state.lower()
    if low in ("cerrado", "cerrar juli", "cancelado"):
        return "Cerrado"
    if low == "rechazado":
        return "Rechazado"
    if "progreso" in low or ("comenz" in low and low != "no comenzado"):
        return "En progreso"
    if low in ("no comenzado", "no iniciado", "abierto"):
        return "Nuevo"
    return "Pendiente" if state else "Nuevo"


def extract_provider_name(sheet: str, notes: list[str]) -> str:
    for note in notes:
        if normalized(note).startswith("proveedor"):
            name = note.split(":", 1)[-1].strip().split("|", 1)[0].strip()
            if name:
                return name
    return sheet.strip()


def row_value(row: tuple[Any, ...], columns: dict[str, int], field: str) -> Any:
    index = columns.get(field)
    return row[index] if index is not None and index < len(row) else None


def operational_note(field: str, value: Any, fecha: str) -> dict[str, Any] | None:
    text = clean(value)
    if not text:
        return None
    return {
        "autor": "Migración InvGate",
        "fecha": fecha,
        "tipo": "comentario_operativo",
        "campo": field,
        "texto": text,
    }


def build_tickets(input_path: Path, start_id: int, only_open: bool) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    wb = load_workbook(input_path, data_only=True, read_only=True)
    tickets: list[dict[str, Any]] = []
    skipped: Counter[str] = Counter()
    by_sheet: Counter[str] = Counter()
    by_state: Counter[str] = Counter()
    next_id = start_id

    for worksheet in wb.worksheets:
        limit = min(worksheet.max_row, MAX_SCAN_ROWS)
        rows = list(worksheet.iter_rows(min_row=1, max_row=limit, max_col=min(worksheet.max_column, 25), values_only=True))
        sheet = worksheet.title.strip()
        header_idx = find_header(rows)
        if header_idx is None:
            skipped["sin_header"] += 1
            continue
        try:
            columns = resolve_columns(rows[header_idx])
        except ValueError:
            skipped["header_invalido"] += 1
            continue

        metadata: list[str] = []
        for row in rows[header_idx + 1 :]:
            for value in (clean(cell) for cell in row[:6] if clean(cell)):
                if normalized(value).startswith(METADATA_PREFIXES):
                    metadata.append(value)
        provider = extract_provider_name(sheet, metadata)

        for row_number, row in enumerate(rows[header_idx + 1 :], start=header_idx + 2):
            if not any(clean(cell) for cell in row[:12]):
                continue
            first_value = normalized(row[0] if row else "")
            if first_value.startswith(METADATA_PREFIXES):
                skipped["fila_metadato"] += 1
                continue

            raw_description = row_value(row, columns, "solicitud")
            raw_ticket = row_value(row, columns, "nro_ticket")
            description = clean(raw_description)
            invgate_id = clean(raw_ticket)
            # A supplier/branch directory row has neither a request nor a numeric ticket.
            if not description and not is_numeric_ticket(raw_ticket):
                skipped["fila_catalogo_o_metadato"] += 1
                continue

            sucursal, sucursal_num = norm_sucursal(row_value(row, columns, "sucursal"))
            if not sucursal:
                skipped["fila_sin_sucursal"] += 1
                continue
            estado_original = clean(row_value(row, columns, "estado"))
            estado = map_estado(estado_original)
            if only_open and estado in {"Cerrado", "Resuelto", "Rechazado"}:
                skipped["cerrados_por_only_open"] += 1
                continue

            categoria, subcategoria = classify(sheet, description)
            prioridad_raw = clean(row_value(row, columns, "prioridad"))
            try:
                prioridad = int(float(prioridad_raw)) if prioridad_raw else 4
            except ValueError:
                prioridad = 4
            prioridad = min(max(prioridad, 1), 4)

            creado = parsed_iso_date(row_value(row, columns, "fecha_solicitud")) or DETERMINISTIC_FALLBACK_DATE
            realization_raw = row_value(row, columns, "fecha_realizacion")
            realization_date = parsed_iso_date(realization_raw)
            actualizado = realization_date or creado
            notes: list[dict[str, Any]] = [{
                "autor": "Migración InvGate",
                "fecha": creado,
                "tipo": "procedencia",
                "texto": f"Importado desde Excel {input_path.name}, hoja {sheet}, fila {row_number}."
                + (f" Ticket InvGate #{invgate_id}." if invgate_id else ""),
            }]
            if clean(realization_raw) and not realization_date:
                note = operational_note("fecha_realizacion_o_consulta", realization_raw, creado)
                if note:
                    notes.append(note)
            for field in ("demora_ticket", "materiales", "ubicacion_materiales"):
                note = operational_note(field, row_value(row, columns, field), creado)
                if note:
                    notes.append(note)

            materiales = clean(row_value(row, columns, "materiales"))
            ubicacion = clean(row_value(row, columns, "ubicacion_materiales"))
            ticket = {
                "id": next_id,
                "sucursal": sucursal,
                "sucursal_num": sucursal_num,
                "categoria": categoria,
                "subcategoria": subcategoria,
                "descripcion": description or f"Ticket InvGate {invgate_id}",
                "solicitante": "Migración InvGate",
                "prioridad": prioridad,
                "estado": estado,
                "asignado": provider if provider != "Personal Mto." else "Equipo Central",
                "fotos": [],
                "observaciones": "",
                "creado": creado,
                "actualizado": actualizado,
                "origen": "InvGate",
                "invgate_ticket_id": invgate_id if is_numeric_ticket(raw_ticket) else "",
                "invgate_estado_original": estado_original,
                "invgate_hoja": sheet,
                "invgate_fila_excel": row_number,
                "proveedor_presupuesto": provider,
                "provincia_origen": clean(row_value(row, columns, "provincia")),
                "materiales_origen": materiales,
                "ubicacion_materiales_origen": ubicacion,
                "notas": notes,
            }
            tickets.append(ticket)
            by_sheet[sheet] += 1
            by_state[estado] += 1
            next_id += 1

    report = {
        "source": str(input_path),
        "total_tickets": len(tickets),
        "by_sheet": dict(sorted(by_sheet.items())),
        "by_state": dict(sorted(by_state.items())),
        "skipped": dict(sorted(skipped.items())),
        "only_open": only_open,
        "start_id": start_id,
    }
    return tickets, report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="InvGate Excel workbook")
    parser.add_argument("--output", type=Path, default=Path("data/tickets_invgate_migration_draft.json"))
    parser.add_argument("--start-id", type=int, default=100001)
    parser.add_argument("--only-open", action="store_true", help="Skip closed/rejected tickets")
    args = parser.parse_args()

    tickets, report = build_tickets(args.input, args.start_id, args.only_open)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(tickets, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"draft: {args.output}")


if __name__ == "__main__":
    main()
