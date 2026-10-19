"""Import a complete, explicitly selected TECMAN JSON snapshot into PostgreSQL.

The command is intentionally fail-closed: it validates every source document and
an operator-supplied backup checksum before importing the application or opening
a database transaction.
"""
import argparse
import hashlib
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


class PreflightError(ValueError):
    """The migration inputs are incomplete or unsafe; the database was untouched."""


@dataclass(frozen=True)
class ListSource:
    filename: str
    label: str
    root_key: Optional[str] = None


LIST_SOURCES = (
    ListSource("tickets.json", "tickets"),
    ListSource("matafuegos.json", "matafuegos", "matafuegos"),
    ListSource("matafuegos_visitas.json", "matafuegos_visitas", "visitas"),
    ListSource("fumigaciones.json", "fumigaciones", "visitas"),
    ListSource("grupos_electrogenos.json", "grupos_electrogenos", "grupos_electrogenos"),
    ListSource("habilitaciones.json", "habilitaciones", "habilitaciones"),
    ListSource("comprobantes.json", "comprobantes", "comprobantes"),
    ListSource("stock_movimientos.json", "stock_movimientos", "movimientos"),
    ListSource("notif_admin.json", "notif_admin", "notificaciones"),
    ListSource("alertas_syh.json", "alertas_syh", "alertas"),
    ListSource("syh_gestiones.json", "syh_gestiones", "gestiones"),
    ListSource("stock_lotes.json", "lotes_fifo", "lotes"),
)
CONFIG_SOURCES = (
    ("stock.json", "stock", dict),
    ("syh.json", "syh", dict),
    ("alertas_syh_dispatch.json", "alertas_syh_dispatch", dict),
)


def _read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PreflightError(f"Falta el archivo requerido: {path.name}") from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PreflightError(f"JSON inválido o ilegible: {path.name}: {exc}") from exc


def _extract_items(raw, spec):
    # fumigaciones historically accepted either a flat list or {"visitas": [...]}.
    if spec.filename == "fumigaciones.json" and isinstance(raw, list):
        items = raw
    elif spec.root_key is None:
        items = raw
    elif isinstance(raw, dict):
        if spec.root_key not in raw:
            raise PreflightError(f"{spec.filename}: falta la clave {spec.root_key!r}")
        items = raw[spec.root_key]
    else:
        items = None
    if not isinstance(items, list):
        raise PreflightError(f"{spec.filename}: se esperaba una lista de registros")
    if not all(isinstance(item, dict) for item in items):
        raise PreflightError(f"{spec.filename}: todos los registros deben ser objetos JSON")
    ids = []
    for index, item in enumerate(items):
        value = item.get("id")
        if value is None or not str(value).strip():
            raise PreflightError(f"{spec.filename}: registro {index} sin id explícito")
        ids.append(str(value))
    if len(ids) != len(set(ids)):
        raise PreflightError(f"{spec.filename}: contiene ids duplicados")
    return items


def verify_backup(path, expected_sha256):
    backup = Path(path).expanduser().resolve()
    if not backup.is_file():
        raise PreflightError("El backup requerido no existe o no es un archivo regular")
    if backup.stat().st_size <= 0:
        raise PreflightError("El backup requerido está vacío")
    expected = str(expected_sha256 or "").strip().lower()
    if len(expected) != 64 or any(ch not in "0123456789abcdef" for ch in expected):
        raise PreflightError("--backup-sha256 debe ser un SHA-256 hexadecimal de 64 caracteres")
    digest = hashlib.sha256()
    with backup.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    actual = digest.hexdigest()
    if actual != expected:
        raise PreflightError(f"El SHA-256 del backup no coincide (obtenido {actual})")
    return backup, actual


def preflight(source_dir, backup_path, backup_sha256):
    source = Path(source_dir).expanduser().resolve()
    if not source.is_dir():
        raise PreflightError("--source-dir debe apuntar a un directorio existente")
    backup, digest = verify_backup(backup_path, backup_sha256)
    if backup == source or source in backup.parents:
        raise PreflightError("El backup debe ser un archivo separado del directorio fuente")

    lists = {}
    for spec in LIST_SOURCES:
        lists[spec.label] = _extract_items(_read_json(source / spec.filename), spec)
    configs = {}
    for filename, key, expected_type in CONFIG_SOURCES:
        value = _read_json(source / filename)
        if not isinstance(value, expected_type):
            raise PreflightError(f"{filename}: se esperaba un objeto JSON")
        configs[key] = value
    return {"source": source, "backup": backup, "backup_sha256": digest,
            "lists": lists, "configs": configs}


def _parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", required=True, help="Directorio explícito del snapshot JSON completo")
    parser.add_argument("--backup", required=True, help="Backup previo, no vacío y separado de la fuente")
    parser.add_argument("--backup-sha256", required=True, help="SHA-256 esperado del backup previo")
    return parser


def migrate(snapshot, database_url):
    if not database_url:
        raise PreflightError("DATABASE_URL no está seteada")
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    if not database_url.startswith(("postgresql://", "postgresql+")):
        raise PreflightError("DATABASE_URL debe apuntar explícitamente a PostgreSQL")

    # Imported only after the complete filesystem/backup preflight has succeeded.
    from flask import Flask
    from models import (db, TicketDB, MatafuegoDB, MatafuegoVisitaDB,
                        GrupoElectrogenoDB, FumigacionDB, HabilitacionDB,
                        ComprobanteDB, StockMovimientoDB, NotifAdminDB,
                        AlertaSyhDB, SyhGestionDB, LoteFifoDB, ConfigDB)

    model_by_label = {
        "tickets": TicketDB,
        "matafuegos": MatafuegoDB,
        "matafuegos_visitas": MatafuegoVisitaDB,
        "fumigaciones": FumigacionDB,
        "grupos_electrogenos": GrupoElectrogenoDB,
        "habilitaciones": HabilitacionDB,
        "comprobantes": ComprobanteDB,
        "stock_movimientos": StockMovimientoDB,
        "notif_admin": NotifAdminDB,
        "alertas_syh": AlertaSyhDB,
        "syh_gestiones": SyhGestionDB,
        "lotes_fifo": LoteFifoDB,
    }
    flask_app = Flask("tecman-json-migration")
    flask_app.config.update(SQLALCHEMY_DATABASE_URI=database_url,
                            SQLALCHEMY_TRACK_MODIFICATIONS=False)
    db.init_app(flask_app)

    with flask_app.app_context():
        try:
            # No create_all(): the destination schema must already exist. Every
            # delete/insert/config replacement below is committed exactly once.
            for label, items in snapshot["lists"].items():
                model = model_by_label[label]
                db.session.query(model).delete(synchronize_session=False)
                for item in items:
                    db.session.add(model.from_dict(item))
            for key, value in snapshot["configs"].items():
                row = db.session.get(ConfigDB, key)
                if row is None:
                    db.session.add(ConfigDB(key=key, value=value))
                else:
                    row.value = value
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise


def main(argv=None):
    args = _parser().parse_args(argv)
    try:
        snapshot = preflight(args.source_dir, args.backup, args.backup_sha256)
        migrate(snapshot, os.environ.get("DATABASE_URL", "").strip())
    except PreflightError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(f"Migración completada en una transacción. Backup verificado: {snapshot['backup_sha256']}")
    for label, items in snapshot["lists"].items():
        print(f"  {label}: {len(items)} registros")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
