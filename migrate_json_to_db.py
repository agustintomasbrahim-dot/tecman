"""
Migración one-shot: importa los JSON de datos a PostgreSQL.
Ejecutar una sola vez después de crear la DB en Render:

    DATABASE_URL=<tu_url> python migrate_json_to_db.py
"""
import os
import sys
import json
from pathlib import Path

DATABASE_URL = os.environ.get("DATABASE_URL", "")
if not DATABASE_URL:
    print("ERROR: DATABASE_URL no está seteada.")
    sys.exit(1)

if DATABASE_URL.startswith("postgres://"):
    os.environ["DATABASE_URL"] = DATABASE_URL.replace("postgres://", "postgresql://", 1)

from app import app, USE_DB
from models import (db, TicketDB, MatafuegoDB, HabilitacionDB, ComprobanteDB,
                    StockMovimientoDB, NotifAdminDB, AlertaSyhDB, SyhGestionDB,
                    VehiculoDB, PermisoDB, PresupuestoDB, CeyhRetiroDB,
                    CeyhJornadaDB, LoteFifoDB, TransferDB, ConfigDB)


def load_json(path, default):
    p = Path(path)
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            pass
    return default


def migrate_list(model, items, label):
    db.session.query(model).delete()
    count = 0
    for item in items:
        db.session.add(model.from_dict(item))
        count += 1
    db.session.commit()
    print(f"  {label}: {count} registros migrados")


def migrate_config(key, value, label):
    row = ConfigDB.query.get(key)
    if row:
        row.value = value
    else:
        db.session.add(ConfigDB(key=key, value=value))
    db.session.commit()
    print(f"  {label}: OK")


DATA = Path(__file__).parent / "data"

with app.app_context():
    db.create_all()
    print("Tablas creadas/verificadas.")

    # Tickets (lista plana)
    tickets = load_json(DATA / "tickets.json", [])
    migrate_list(TicketDB, tickets, "tickets")

    # Matafuegos
    data = load_json(DATA / "matafuegos.json", {"matafuegos": []})
    migrate_list(MatafuegoDB, data.get("matafuegos", []), "matafuegos")

    # Habilitaciones
    data = load_json(DATA / "habilitaciones.json", {"habilitaciones": []})
    migrate_list(HabilitacionDB, data.get("habilitaciones", []), "habilitaciones")

    # Comprobantes
    data = load_json(DATA / "comprobantes.json", {"comprobantes": []})
    migrate_list(ComprobanteDB, data.get("comprobantes", []), "comprobantes")

    # Stock movimientos
    data = load_json(DATA / "stock_movimientos.json", {"movimientos": []})
    migrate_list(StockMovimientoDB, data.get("movimientos", []), "stock_movimientos")

    # Notif admin
    data = load_json(DATA / "notif_admin.json", {"notificaciones": []})
    migrate_list(NotifAdminDB, data.get("notificaciones", []), "notif_admin")

    # Alertas SyH
    data = load_json(DATA / "alertas_syh.json", {"alertas": []})
    migrate_list(AlertaSyhDB, data.get("alertas", []), "alertas_syh")

    # SyH gestiones
    data = load_json(DATA / "syh_gestiones.json", {"gestiones": []})
    migrate_list(SyhGestionDB, data.get("gestiones", []), "syh_gestiones")

    # Lotes FIFO
    data = load_json(DATA / "stock_lotes.json", {"lotes": []})
    migrate_list(LoteFifoDB, data.get("lotes", []), "lotes_fifo")

    # Config: stock
    stock = load_json(DATA / "stock.json", {"central": {}, "sucursales": {}})
    migrate_config("stock", stock, "stock")

    # Config: syh (por sucursal)
    syh = load_json(DATA / "syh.json", {})
    migrate_config("syh", syh, "syh")

    # Config: alertas dispatch
    dispatch = load_json(DATA / "alertas_syh_dispatch.json", {"sent": {}})
    migrate_config("alertas_syh_dispatch", dispatch, "alertas_syh_dispatch")

    print("\nMigración completada.")
