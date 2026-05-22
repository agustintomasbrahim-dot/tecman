"""Tecman - Sistema de tickets de mantenimiento para Grupo Dabra"""

import os
import io
import json
import uuid
import zipfile
import datetime
import shutil
import smtplib
import ssl
from pathlib import Path
from functools import wraps
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, send_from_directory, Response

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "tecman-dev-key-2026")

# PostgreSQL via SQLAlchemy (dual-write con fallback a JSON)
_DB_URL = os.environ.get("DATABASE_URL", "")
if _DB_URL.startswith("postgres://"):
    _DB_URL = _DB_URL.replace("postgres://", "postgresql://", 1)
USE_DB = False
if _DB_URL:
    try:
        from models import (db, TicketDB, MatafuegoDB, HabilitacionDB, ComprobanteDB,
                            StockMovimientoDB, NotifAdminDB, AlertaSyhDB, SyhGestionDB,
                            VehiculoDB, PermisoDB, PresupuestoDB, CeyhRetiroDB,
                            CeyhJornadaDB, LoteFifoDB, TransferDB, ConfigDB)
        app.config["SQLALCHEMY_DATABASE_URI"] = _DB_URL
        app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
        db.init_app(app)
        with app.app_context():
            db.create_all()
        USE_DB = True
    except Exception as e:
        print(f"[WARN] DB no disponible, usando JSON: {e}")

IS_CLOUD = os.environ.get("RENDER", False)

# En Render usamos el disco persistente montado en /data
# En local usamos ./data relativo al proyecto
if IS_CLOUD and Path("/data").exists():
    DATA_DIR = Path("/data")
else:
    DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)

TICKETS_FILE = DATA_DIR / "tickets.json"
SYH_GESTIONES_FILE = DATA_DIR / "syh_gestiones.json"
STOCK_FILE = DATA_DIR / "stock.json"
TRANSFERS_FILE = DATA_DIR / "transfers.json"
COMPROBANTES_FILE = DATA_DIR / "comprobantes.json"
NOTIF_ADMIN_FILE = DATA_DIR / "notif_admin.json"
STOCK_MOV_FILE = DATA_DIR / "stock_movimientos.json"
STOCK_LOTES_FILE = DATA_DIR / "stock_lotes.json"
GUIAS_COUNTER_FILE = DATA_DIR / "guias_counter.json"
HABILITACIONES_FILE = DATA_DIR / "habilitaciones.json"
MATAFUEGOS_FILE = DATA_DIR / "matafuegos.json"
VEHICULOS_FILE = DATA_DIR / "vehiculos_equipo.json"
PERMISOS_FILE = DATA_DIR / "permisos.json"
ALERTAS_SYH_FILE = DATA_DIR / "alertas_syh.json"
ALERTAS_SYH_DISPATCH_FILE = DATA_DIR / "alertas_syh_dispatch.json"
PRESUPUESTOS_FILE = DATA_DIR / "presupuestos.json"
CEYH_RETIROS_FILE = DATA_DIR / "ceyh_retiros.json"
CEYH_JORNADAS_FILE = DATA_DIR / "ceyh_jornadas.json"

# Uploads: también en disco persistente en Render
if IS_CLOUD and Path("/data").exists():
    UPLOADS_DIR = Path("/data") / "uploads"
else:
    UPLOADS_DIR = Path(__file__).parent / "static" / "uploads"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
COMPROBANTES_DIR = UPLOADS_DIR / "comprobantes"
COMPROBANTES_DIR.mkdir(parents=True, exist_ok=True)
GUIAS_DIR = UPLOADS_DIR / "guias"
GUIAS_DIR.mkdir(parents=True, exist_ok=True)
HABILITACIONES_DIR = UPLOADS_DIR / "habilitaciones"
HABILITACIONES_DIR.mkdir(parents=True, exist_ok=True)
TRABAJOS_DIR = UPLOADS_DIR / "trabajos"
TRABAJOS_DIR.mkdir(parents=True, exist_ok=True)
PERMISOS_DIR = UPLOADS_DIR / "permisos"
PERMISOS_DIR.mkdir(parents=True, exist_ok=True)
PRESUPUESTOS_DIR = UPLOADS_DIR / "presupuestos"
PRESUPUESTOS_DIR.mkdir(parents=True, exist_ok=True)
REQUISICIONES_DIR = UPLOADS_DIR / "requisiciones"
REQUISICIONES_DIR.mkdir(parents=True, exist_ok=True)

# --- Data ---

SUCURSALES = [
    "Central - Dabra", "Garin",
    "Sucursal 011", "Sucursal 014", "Sucursal 020", "Sucursal 023", "Sucursal 028",
    "Sucursal 035", "Sucursal 036", "Sucursal 043", "Sucursal 049",
    "Sucursal 051", "Sucursal 052", "Sucursal 053", "Sucursal 054",
    "Sucursal 058", "Sucursal 065", "Sucursal 076", "Sucursal 077",
    "Sucursal 078", "Sucursal 080", "Sucursal 082", "Sucursal 083",
    "Sucursal 091", "Sucursal 092", "Sucursal 102", "Sucursal 111",
    "Sucursal 114", "Sucursal 116", "Sucursal 120", "Sucursal 121", "Sucursal 123",
    "Sucursal 124", "Sucursal 125", "Sucursal 126", "Sucursal 127", "Sucursal 128",
    "Sucursal 132", "Sucursal 133", "Sucursal 134", "Sucursal 139", "Sucursal 141", "Sucursal 142", "Sucursal 145",
    "Sucursal 146", "Sucursal 147", "Sucursal 148", "Sucursal 156",
    "Sucursal 157", "Sucursal 158", "Sucursal 159", "Sucursal 160",
    "Sucursal 165", "Sucursal 166", "Sucursal 167", "Sucursal 170",
    "Sucursal 171", "Sucursal 172", "Sucursal 173", "Sucursal 176",
    "Sucursal 177", "Sucursal 178", "Sucursal 183", "Sucursal 184",
    "Sucursal 185", "Sucursal 186", "Sucursal 187", "Sucursal 188",
    "Sucursal 190", "Sucursal 191", "Sucursal 192", "Sucursal 193",
    "Sucursal 194", "Sucursal 195", "Sucursal 196", "Sucursal 198", "Sucursal 199",
    "Sucursal 200", "Sucursal 202", "Sucursal 203", "Sucursal 204",
    "Sucursal 205", "Sucursal 206", "Sucursal 207", "Sucursal 208",
    "Sucursal 209", "Sucursal 210", "Sucursal 211", "Sucursal 212", "Sucursal 213",
    "Sucursal 214", "Sucursal 215", "Sucursal 216", "Sucursal 217",
    "Sucursal 219", "Sucursal 220", "Sucursal 221", "Sucursal 222", "Sucursal 224",
    "Sucursal 226", "Sucursal 228", "Sucursal 229", "Sucursal 230", "Sucursal 231",
    "Sucursal 232", "Sucursal 233", "Sucursal 234", "Sucursal 235", "Sucursal 236",
    "Sucursal 237", "Sucursal 238", "Sucursal 239", "Sucursal 240",
    "Sucursal 241",
]

CATEGORIAS = {
    "Problema Eléctrico": ["Luminarias", "Tablero", "Cableado", "Tomas", "Otro eléctrico"],
    "Plomería": ["Agua fría", "Agua caliente", "Pérdidas en cañerías", "Pérdidas en canillas", "Otro plomería"],
    "Filtraciones": ["Por lluvia", "Por azotea", "Por membrana", "Por muros/humedad", "Por alcantarillas", "Otra filtración"],
    "Aire Acondicionado": ["Sin funcionamiento", "Reparación", "Goteo", "Limpieza", "Instalación", "Otro AA"],
    "Pintura": ["Interior", "Exterior", "Durlock reparación", "Otra pintura"],
    "Reparaciones": ["General", "Persianas", "Candados", "Ascensor", "Otra reparación"],
    "Materiales": ["Solicitud de materiales"],
    "Presupuestos": ["Cortinas", "Filtraciones", "Aire acondicionado", "Electricidad", "Pintura", "Plomería", "Carpintería", "Vidriería", "Matafuegos", "Habilitaciones", "Otro presupuesto"],
    "Seguridad e Higiene": ["Consulta de habilitación", "Permiso", "Documentación faltante", "Otra asistencia S&H"],
    "Otro": ["Otro"],
}

PRIORIDADES = {
    1: "Urgente",
    2: "Alta",
    3: "Media",
    4: "Baja",
}

ESTADOS = ["Nuevo", "Abierto", "En progreso", "Materiales recibidos", "Pendiente", "Aprobado", "Rechazado", "Resuelto", "Cerrado"]

_ADMIN_PWD = os.environ.get("ADMIN_PASSWORD", "tecman2026")
_COMPRAS_PWD = os.environ.get("COMPRAS_PASSWORD", "compras2026")
_CENTRAL_PWD = os.environ.get("CENTRAL_PASSWORD", "central2026")
COMPRAS_EMAIL = os.environ.get("COMPRAS_EMAIL", "lperonace@grupodexter.com.ar,gpeirano@grupodexter.com.ar")
PATRICIA_EMAIL = os.environ.get("PATRICIA_EMAIL", "pperez@grupodexter.com.ar")
GMAIL_USER = os.environ.get("GMAIL_USER", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
SUCURSAL_EMAILS = {
    "011": "suc011@grupodabra.com.ar",
    "014": "suc014@grupodabra.com.ar",
    "020": "suc020@grupodabra.com.ar",
    "023": "suc023@grupodabra.com.ar",
    "028": "suc028@grupodabra.com.ar",
    "035": "suc035@grupodabra.com.ar",
    "036": "suc036@grupodabra.com.ar",
    "043": "suc043@grupodabra.com.ar",
    "049": "suc049@grupodabra.com.ar",
    "051": "suc051@grupodabra.com.ar",
    "052": "suc052@grupodabra.com.ar",
    "053": "suc053@grupodabra.com.ar",
    "054": "suc054@grupodabra.com.ar",
    "058": "suc058@grupodabra.com.ar",
    "065": "suc065@grupodabra.com.ar",
    "076": "suc076@grupodabra.com.ar",
    "077": "suc077@grupodabra.com.ar",
    "078": "suc078@grupodabra.com.ar",
    "080": "suc080@grupodabra.com.ar",
    "082": "suc082@grupodabra.com.ar",
    "083": "suc083@grupodabra.com.ar",
    "091": "suc091@grupodabra.com.ar",
    "092": "suc092@grupodabra.com.ar",
    "102": "suc102@grupodabra.com.ar",
    "111": "suc111@grupodabra.com.ar",
    "114": "suc114@grupodabra.com.ar",
    "116": "suc116@grupodabra.com.ar",
    "120": "suc120@grupodabra.com.ar",
    "121": "suc121@grupodabra.com.ar",
    "123": "suc123@grupodabra.com.ar",
    "124": "suc124@grupodabra.com.ar",
    "125": "suc125@grupodabra.com.ar",
    "126": "suc126@grupodabra.com.ar",
    "127": "suc127@grupodabra.com.ar",
    "128": "suc128@grupodabra.com.ar",
    "132": "suc132@grupodabra.com.ar",
    "133": "suc133@grupodabra.com.ar",
    "134": "suc134@grupodabra.com.ar",
    "135": "suc135@grupodabra.com.ar",
    "139": "suc139@grupodabra.com.ar",
    "141": "suc141@grupodabra.com.ar",
    "142": "suc142@grupodabra.com.ar",
    "145": "suc145@grupodabra.com.ar",
    "146": "suc146@grupodabra.com.ar",
    "147": "suc147@grupodabra.com.ar",
    "148": "suc148@grupodabra.com.ar",
    "156": "suc156@grupodabra.com.ar",
    "157": "suc157@grupodabra.com.ar",
    "158": "suc158@grupodabra.com.ar",
    "159": "suc159@grupodabra.com.ar",
    "160": "suc160@grupodabra.com.ar",
    "165": "suc165@grupodabra.com.ar",
    "166": "suc166@grupodabra.com.ar",
    "167": "suc167@grupodabra.com.ar",
    "170": "suc170@grupodabra.com.ar",
    "171": "suc171@grupodabra.com.ar",
    "172": "suc172@grupodabra.com.ar",
    "173": "suc173@grupodabra.com.ar",
    "176": "suc176@grupodabra.com.ar",
    "177": "suc177@grupodabra.com.ar",
    "178": "suc178@grupodabra.com.ar",
    "183": "suc183@grupodabra.com.ar",
    "184": "suc184@grupodabra.com.ar",
    "185": "suc185@grupodabra.com.ar",
    "186": "suc186@grupodabra.com.ar",
    "187": "suc187@grupodabra.com.ar",
    "188": "suc188@grupodabra.com.ar",
    "190": "suc190@grupodabra.com.ar",
    "191": "suc191@grupodabra.com.ar",
    "192": "suc192@grupodabra.com.ar",
    "193": "suc193@grupodabra.com.ar",
    "194": "suc194@grupodabra.com.ar",
    "195": "suc195@grupodabra.com.ar",
    "196": "suc196@grupodabra.com.ar",
    "198": "suc198@grupodabra.com.ar",
    "199": "suc199@grupodabra.com.ar",
    "200": "suc200@grupodabra.com.ar",
    "202": "suc202@grupodabra.com.ar",
    "203": "suc203@grupodabra.com.ar",
    "204": "suc204@grupodabra.com.ar",
    "205": "suc205@grupodabra.com.ar",
    "206": "suc206@grupodabra.com.ar",
    "207": "suc207@grupodabra.com.ar",
    "208": "suc208@grupodabra.com.ar",
    "209": "suc209@grupodabra.com.ar",
    "210": "suc210@grupodabra.com.ar",
    "211": "suc211@grupodabra.com.ar",
    "212": "suc212@grupodabra.com.ar",
    "213": "suc213@grupodabra.com.ar",
    "214": "suc214@grupodabra.com.ar",
    "215": "suc215@grupodabra.com.ar",
    "216": "suc216@grupodabra.com.ar",
    "217": "suc217@grupodabra.com.ar",
    "219": "suc219@grupodabra.com.ar",
    "220": "suc220@grupodabra.com.ar",
    "221": "suc221@grupodabra.com.ar",
    "222": "suc222@grupodabra.com.ar",
    "223": "suc223@grupodabra.com.ar",
    "224": "suc224@grupodabra.com.ar",
    "226": "suc226@grupodabra.com.ar",
    "228": "suc228@grupodabra.com.ar",
    "229": "suc229@grupodabra.com.ar",
    "230": "suc230@grupodabra.com.ar",
    "231": "suc231@grupodabra.com.ar",
    "232": "suc232@grupodabra.com.ar",
    "233": "suc233@grupodabra.com.ar",
    "234": "suc234@grupodabra.com.ar",
    "235": "suc235@grupodexter.com.ar",
    "236": "suc236@grupodabra.com.ar",
    "237": "suc237@grupodabra.com.ar",
    "238": "suc238@grupodexter.com.ar",
    "239": "suc239@grupodexter.com.ar",
    "240": "suc240@grupodexter.com.ar",
    "241": "suc241@grupodexter.com.ar",
}

ADMINS = {
    "agustin": {"password": _ADMIN_PWD, "nombre": "Agustín Brahim", "rol": "admin"},
    "carolina": {"password": _ADMIN_PWD, "nombre": "Carolina", "rol": "admin"},
    "jonathan": {"password": _ADMIN_PWD, "nombre": "Jonatan", "rol": "tecnico"},
    "patricia": {"password": _ADMIN_PWD, "nombre": "Patricia", "rol": "syh"},
    "rita": {"password": _ADMIN_PWD, "nombre": "Rita", "rol": "admin"},
}

# Portal de Compras (Laura). Portal separado del de admin.
COMPRAS_USERS = {
    "laura": {"password": _COMPRAS_PWD, "nombre": "Laura", "rol": "compras"},
}

# Portal Equipo de Mantenimiento Central (Hector y Jose)
EQUIPO_USERS = {
    "equipo": {"password": _CENTRAL_PWD, "nombre": "Equipo Central", "rol": "equipo_central"},
}

SYH_FILE = DATA_DIR / "syh.json"

SYH_ESTADOS = {
    "habilitacion": ["Vigente", "Vencida", "En tramite", "Sin habilitacion"],
    "bomberos": ["Aprobado", "Pendiente", "Vencido", "Sin tramitar"],
    "matafuegos": ["Al dia", "Proximo a vencer", "Vencidos", "Sin datos"],
    "red_incendio": ["Si", "No", "Parcial", "Sin datos"],
    "plano_evacuacion": ["Tiene", "No tiene"],
    "senalizacion": ["Completa", "Incompleta", "Sin datos"],
}

def load_syh():
    if USE_DB:
        return _db_cfg_get("syh", {})
    if SYH_FILE.exists():
        try:
            return json.loads(SYH_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {}

def _atomic_write(path: Path, data) -> None:
    content = json.dumps(data, indent=2, ensure_ascii=False)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


# --- Helpers DB (sólo se llaman cuando USE_DB es True) ---

def _db_replace(model, items):
    db.session.query(model).delete()
    for item in items:
        db.session.add(model.from_dict(item))
    db.session.commit()

def _db_list(model):
    return [r.to_dict() for r in model.query.all()]

def _db_cfg_get(key, default):
    row = ConfigDB.query.get(key)
    return row.value if row else default

def _db_cfg_set(key, value):
    row = ConfigDB.query.get(key)
    if row:
        row.value = value
    else:
        db.session.add(ConfigDB(key=key, value=value))
    db.session.commit()


def save_syh(data):
    if USE_DB:
        _db_cfg_set("syh", data)
    _atomic_write(SYH_FILE, data)


SYH_DOCUMENTOS_CATEGORIAS = [
    ("habilitaciones", "Habilitaciones"),
    ("planos_municipales", "Planos municipales"),
    ("planos_electromecanicos", "Planos electromecánicos"),
    ("planos_bomberos_mas_1000", "Planos de bomberos sup. mayores a 1000 mts"),
    ("doc_seg_hig_ministerio_art", "Documentación de seg. e higiene / ministerio de trabajo / ART"),
    ("protocolo_puesta_tierra_iluminacion", "Protocolo de puesta a tierra e iluminación"),
    ("plan_evacuacion", "Plan de evacuación"),
    ("plano_evacuacion_doc", "Plano de evacuación"),
    ("carga_de_fuego", "Carga de fuego"),
    ("antisiniestral", "Antisiniestral"),
    ("capacitaciones", "Capacitaciones"),
]

SYH_CAPACITACIONES_SUBTIPOS = [
    "Uso de extintores",
    "RCP",
    "Manejo de cargas",
    "Primeros auxilios",
    "Riesgo de las tareas",
]


def _build_syh_documentos_detallados(form, files, suc_num, estado):
    existentes = list(estado.get("documentos_detallados", []) or [])
    nuevos = []
    ahora = datetime.datetime.now().isoformat()
    for categoria, _label in SYH_DOCUMENTOS_CATEGORIAS:
        for f in files.getlist(f"documento_{categoria}"):
            if not f or not f.filename:
                continue
            ext = Path(f.filename).suffix.lower()
            if ext not in (".pdf", ".jpg", ".jpeg", ".png", ".gif", ".webp"):
                continue
            fname = f"syh_{suc_num}_{categoria}_{uuid.uuid4().hex[:8]}{ext}"
            f.save(str(UPLOADS_DIR / fname))
            item = {
                "categoria": categoria,
                "categoria_label": dict(SYH_DOCUMENTOS_CATEGORIAS).get(categoria, categoria),
                "nombre": f.filename,
                "archivo": fname,
                "fecha": ahora,
            }
            if categoria == "capacitaciones":
                item["subtipo"] = form.get(f"capacitacion_tipo_{categoria}", "").strip()
            nuevos.append(item)
    return existentes + nuevos

def _stock_entry(val):
    """Normaliza un valor de stock central al formato {cantidad, precio_unitario}.
    Compatible con formato viejo (int/float)."""
    if isinstance(val, dict):
        try:
            cantidad = int(val.get("cantidad", 0) or 0)
        except (TypeError, ValueError):
            cantidad = 0
        try:
            precio = float(val.get("precio_unitario", 0) or 0)
        except (TypeError, ValueError):
            precio = 0.0
        return {"cantidad": cantidad, "precio_unitario": precio}
    try:
        return {"cantidad": int(val or 0), "precio_unitario": 0.0}
    except (TypeError, ValueError):
        return {"cantidad": 0, "precio_unitario": 0.0}


def load_stock():
    if USE_DB:
        data = _db_cfg_get("stock", {"central": {}, "sucursales": {}})
    elif STOCK_FILE.exists():
        try:
            data = json.loads(STOCK_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            data = {"central": {}, "sucursales": {}}
    else:
        data = {"central": {}, "sucursales": {}}
    central = data.get("central", {}) or {}
    for k in list(central.keys()):
        central[k] = _stock_entry(central[k])
    data["central"] = central
    data.setdefault("sucursales", {})
    return data


def save_stock(data):
    if USE_DB:
        _db_cfg_set("stock", data)
    _atomic_write(STOCK_FILE, data)


def get_central_qty(stock, item):
    e = stock.get("central", {}).get(item)
    return int(e.get("cantidad", 0)) if e else 0


def get_central_precio(stock, item):
    e = stock.get("central", {}).get(item)
    return float(e.get("precio_unitario", 0.0)) if e else 0.0


def set_central_qty(stock, item, cantidad, precio=None):
    """Setea la cantidad del item en central. Si <= 0, lo elimina."""
    central = stock.setdefault("central", {})
    cantidad = int(cantidad)
    if cantidad <= 0:
        central.pop(item, None)
        return
    entry = central.get(item) or {"cantidad": 0, "precio_unitario": 0.0}
    entry["cantidad"] = cantidad
    if precio is not None:
        entry["precio_unitario"] = float(precio)
    central[item] = entry


def set_central_precio(stock, item, precio):
    """Setea el precio_unitario del item en central (creando entrada si hace falta)."""
    central = stock.setdefault("central", {})
    entry = central.get(item) or {"cantidad": 0, "precio_unitario": 0.0}
    entry["precio_unitario"] = float(precio)
    central[item] = entry

def load_transfers():
    if USE_DB:
        return _db_list(TransferDB)
    if TRANSFERS_FILE.exists():
        try:
            return json.loads(TRANSFERS_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return []

def save_transfers(data):
    if USE_DB:
        _db_replace(TransferDB, data)
    _atomic_write(TRANSFERS_FILE, data)

def load_comprobantes():
    if USE_DB:
        return {"comprobantes": _db_list(ComprobanteDB)}
    if COMPROBANTES_FILE.exists():
        try:
            return json.loads(COMPROBANTES_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {"comprobantes": []}

def save_comprobantes(data):
    if USE_DB:
        _db_replace(ComprobanteDB, data.get("comprobantes", []))
    _atomic_write(COMPROBANTES_FILE, data)


def load_notif_admin():
    if USE_DB:
        return {"notificaciones": _db_list(NotifAdminDB)}
    if NOTIF_ADMIN_FILE.exists():
        try:
            return json.loads(NOTIF_ADMIN_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {"notificaciones": []}


def save_notif_admin(data):
    if USE_DB:
        _db_replace(NotifAdminDB, data.get("notificaciones", []))
    _atomic_write(NOTIF_ADMIN_FILE, data)


def agregar_notif_admin(titulo, detalle, tipo="stock", autor="", link=None):
    """Agrega una notificacion al buzon de admins (Agustin / Carolina)."""
    data = load_notif_admin()
    data.setdefault("notificaciones", []).insert(0, {
        "id": uuid.uuid4().hex[:10],
        "tipo": tipo,
        "titulo": titulo,
        "detalle": detalle,
        "autor": autor,
        "link": link,
        "fecha": datetime.datetime.now().isoformat(),
        "leida": False,
    })
    # Mantener solo las ultimas 200
    data["notificaciones"] = data["notificaciones"][:200]
    save_notif_admin(data)

def load_movimientos():
    if USE_DB:
        return {"movimientos": _db_list(StockMovimientoDB)}
    if STOCK_MOV_FILE.exists():
        try:
            return json.loads(STOCK_MOV_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {"movimientos": []}

def save_movimientos(data):
    if USE_DB:
        _db_replace(StockMovimientoDB, data.get("movimientos", []))
    _atomic_write(STOCK_MOV_FILE, data)


# --- FIFO por lotes ---
# Cada lote representa un ingreso fisico real (remito de proveedor) con su
# cantidad y precio unitario. Los egresos a sucursal consumen lotes en orden
# FIFO (fecha_origen asc, luego created_at asc) para imputar el costo real.

def load_lotes_fifo():
    if USE_DB:
        return {"lotes": _db_list(LoteFifoDB)}
    if STOCK_LOTES_FILE.exists():
        try:
            return json.loads(STOCK_LOTES_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {"lotes": []}


def save_lotes_fifo(data):
    if USE_DB:
        _db_replace(LoteFifoDB, data.get("lotes", []))
    _atomic_write(STOCK_LOTES_FILE, data)


def crear_lote_fifo(item, cantidad, precio_unitario, tipo_origen="remito_proveedor",
                    comprobante_id=None, numero_comprobante="", proveedor="",
                    fecha_origen=None):
    """Crea un lote FIFO por un ingreso fisico de stock. Devuelve el lote creado."""
    try:
        cantidad = int(cantidad)
    except (TypeError, ValueError):
        return None
    if not item or cantidad <= 0:
        return None
    try:
        precio_unitario = float(precio_unitario or 0)
    except (TypeError, ValueError):
        precio_unitario = 0.0
    data = load_lotes_fifo()
    lote = {
        "id": uuid.uuid4().hex[:12],
        "item": item,
        "cantidad_original": cantidad,
        "cantidad_disponible": cantidad,
        "precio_unitario": precio_unitario,
        "tipo_origen": tipo_origen or "remito_proveedor",
        "comprobante_id": comprobante_id or "",
        "numero_comprobante": numero_comprobante or "",
        "proveedor": proveedor or "",
        "fecha_origen": (fecha_origen or datetime.date.today().isoformat())[:10],
        "created_at": datetime.datetime.now().isoformat(),
    }
    data.setdefault("lotes", []).append(lote)
    save_lotes_fifo(data)
    return lote


def _lote_sort_key(lote):
    # FIFO: fecha_origen asc, luego created_at asc
    return (lote.get("fecha_origen", "") or "", lote.get("created_at", "") or "")


def consumir_lotes_fifo(item, cantidad):
    """Consume 'cantidad' del item de los lotes FIFO disponibles.

    Devuelve dict con:
      - consumido: int (cantidad efectivamente consumida de lotes)
      - faltante: int (lo que no alcanzo a cubrirse con lotes)
      - breakdown: lista de {lote_id, cantidad, precio_unitario,
                             numero_comprobante, proveedor, fecha_origen,
                             comprobante_id, tipo_origen}
      - precio_promedio: float (promedio ponderado de lo consumido, 0 si nada)
      - monto_total: float (subtotal real consumido de lotes)
    """
    try:
        cantidad = int(cantidad)
    except (TypeError, ValueError):
        cantidad = 0
    result = {
        "consumido": 0,
        "faltante": max(0, cantidad),
        "breakdown": [],
        "precio_promedio": 0.0,
        "monto_total": 0.0,
    }
    if not item or cantidad <= 0:
        return result

    data = load_lotes_fifo()
    lotes = data.get("lotes", [])
    disponibles = [l for l in lotes if l.get("item") == item and int(l.get("cantidad_disponible", 0) or 0) > 0]
    disponibles.sort(key=_lote_sort_key)

    restante = cantidad
    monto_total = 0.0
    changed = False
    for lote in disponibles:
        if restante <= 0:
            break
        disp = int(lote.get("cantidad_disponible", 0) or 0)
        if disp <= 0:
            continue
        tomar = min(disp, restante)
        lote["cantidad_disponible"] = disp - tomar
        precio = float(lote.get("precio_unitario", 0) or 0)
        subtotal = round(tomar * precio, 2)
        monto_total += subtotal
        result["breakdown"].append({
            "lote_id": lote.get("id", ""),
            "cantidad": tomar,
            "precio_unitario": precio,
            "numero_comprobante": lote.get("numero_comprobante", ""),
            "proveedor": lote.get("proveedor", ""),
            "fecha_origen": lote.get("fecha_origen", ""),
            "comprobante_id": lote.get("comprobante_id", ""),
            "tipo_origen": lote.get("tipo_origen", ""),
        })
        restante -= tomar
        changed = True

    consumido = cantidad - restante
    result["consumido"] = consumido
    result["faltante"] = restante
    result["monto_total"] = round(monto_total, 2)
    if consumido > 0:
        result["precio_promedio"] = round(monto_total / consumido, 4)

    if changed:
        save_lotes_fifo(data)
    return result


def _load_guias_counter():
    if GUIAS_COUNTER_FILE.exists():
        try:
            return json.loads(GUIAS_COUNTER_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {"ultimo": 87889}

def _save_guias_counter(data):
    _atomic_write(GUIAS_COUNTER_FILE, data)

def load_habilitaciones():
    if USE_DB:
        return {"habilitaciones": _db_list(HabilitacionDB)}
    if HABILITACIONES_FILE.exists():
        try:
            return json.loads(HABILITACIONES_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {"habilitaciones": []}

def save_habilitaciones(data):
    if USE_DB:
        _db_replace(HabilitacionDB, data.get("habilitaciones", []))
    _atomic_write(HABILITACIONES_FILE, data)

def load_matafuegos():
    if USE_DB:
        return {"matafuegos": _db_list(MatafuegoDB)}
    if MATAFUEGOS_FILE.exists():
        try:
            return json.loads(MATAFUEGOS_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {"matafuegos": []}

def save_matafuegos(data):
    if USE_DB:
        _db_replace(MatafuegoDB, data.get("matafuegos", []))
    _atomic_write(MATAFUEGOS_FILE, data)

def _parse_fecha_matafuego(valor):
    valor = str(valor or "").strip()
    if not valor:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y", "%d-%m-%Y", "%m/%Y", "%m/%y", "%m-%Y", "%m-%y"):
        try:
            dt = datetime.datetime.strptime(valor, fmt)
            if fmt in ("%m/%Y", "%m/%y", "%m-%Y", "%m-%y"):
                return datetime.date(dt.year, dt.month, 1)
            return dt.date()
        except ValueError:
            continue
    return None


def _sumar_un_anio(fecha):
    if not fecha:
        return None
    try:
        return fecha.replace(year=fecha.year + 1)
    except ValueError:
        return fecha + datetime.timedelta(days=365)


def _fecha_control_matafuego(item):
    fecha_carga = _parse_fecha_matafuego(item.get("fecha_carga"))
    if fecha_carga:
        return _sumar_un_anio(fecha_carga), "fecha_carga"
    fecha_venc = _parse_fecha_matafuego(item.get("fecha_vencimiento"))
    if fecha_venc:
        return fecha_venc, "fecha_vencimiento"
    return None, "sin_fecha"


def _estado_matafuego(fecha_control, estado_manual=""):
    estado_manual = (estado_manual or "").strip().lower()
    if estado_manual == "rechazado":
        return "rechazado"
    if not fecha_control:
        return "sin_dato"
    hoy = datetime.date.today()
    if fecha_control < hoy:
        return "vencido"
    if fecha_control <= hoy + datetime.timedelta(days=30):
        return "proximo"
    return "al_dia"


def _enrich_matafuego(m):
    x = dict(m)
    fecha_control, fuente_control = _fecha_control_matafuego(x)
    x["fecha_control_calc"] = fecha_control.isoformat() if fecha_control else ""
    x["fuente_control"] = fuente_control
    x["estado_calc"] = _estado_matafuego(fecha_control, x.get("estado_manual", ""))
    return x

def _stats_matafuegos(items):
    items = [_enrich_matafuego(i) for i in items]
    return {
        "total": len(items),
        "al_dia": sum(1 for i in items if i["estado_calc"] == "al_dia"),
        "proximo": sum(1 for i in items if i["estado_calc"] == "proximo"),
        "vencido": sum(1 for i in items if i["estado_calc"] == "vencido"),
        "rechazado": sum(1 for i in items if i["estado_calc"] == "rechazado"),
    }

def _resumen_matafuegos_sucursal(items):
    items = [_enrich_matafuego(i) for i in items]
    tipos = {}
    proximo_vto = ""
    for i in items:
        tipo = (i.get("tipo") or "Sin tipo").strip() or "Sin tipo"
        tipos[tipo] = tipos.get(tipo, 0) + int(i.get("cantidad") or 1)
        fv = (i.get("fecha_control_calc") or "").strip()
        if fv and (not proximo_vto or fv < proximo_vto):
            proximo_vto = fv
    tipos_txt = ", ".join(f"{k}: {v}" for k, v in sorted(tipos.items())) if tipos else "-"
    stats = _stats_matafuegos(items)
    if stats["vencido"] or stats["rechazado"]:
        estado = "Vencidos"
    elif stats["proximo"]:
        estado = "Proximo a vencer"
    elif items:
        estado = "Al dia"
    else:
        estado = "Sin datos"
    return {
        "cantidad": len(items),
        "tipos": tipos_txt,
        "proximo_vto": proximo_vto,
        "estado": estado,
        "stats": stats,
    }

def sync_alertas_matafuegos():
    data = load_alertas_syh()
    prev_map = {a.get("id"): a for a in data.get("alertas", [])}
    mats = load_matafuegos().get("matafuegos", [])
    por_sucursal = {}
    for m in mats:
        suc = m.get("sucursal_num") or (m.get("sucursal", "").replace("Sucursal ", "").strip())
        if suc:
            por_sucursal.setdefault(suc, []).append(m)

    nuevas_alertas = []
    for suc_num, items in por_sucursal.items():
        resumen = _resumen_matafuegos_sucursal(items)
        if resumen["estado"] not in ("Vencidos", "Proximo a vencer"):
            continue
        aid = f"matafuegos:{suc_num}:{resumen['estado']}"
        alerta = {
            "id": aid,
            "tipo": "matafuegos",
            "sucursal_num": suc_num,
            "estado": resumen["estado"],
            "proximo_vto": resumen.get("proximo_vto", ""),
            "tipos": resumen.get("tipos", ""),
            "cantidad": resumen.get("cantidad", 0),
            "destinatarios": ["Agustín", "Patricia", f"Sucursal {suc_num}"],
            "updated_at": datetime.datetime.now().isoformat(),
        }
        if aid not in prev_map:
            agregar_notif_admin(
                f"🚨 Matafuegos {alerta['estado'].lower()} - Sucursal {suc_num}",
                f"{alerta['cantidad']} cargado(s) · {alerta['tipos']} · Próximo vencimiento: {alerta['proximo_vto'] or '-'}\nAvisar a Patricia y sucursal.",
                tipo="syh_matafuegos",
                autor="Sistema",
                link="/admin/syh",
            )
        elif prev_map[aid].get("proximo_vto") != alerta.get("proximo_vto") or prev_map[aid].get("tipos") != alerta.get("tipos"):
            agregar_notif_admin(
                f"🔄 Actualización matafuegos - Sucursal {suc_num}",
                f"Estado: {alerta['estado']} · {alerta['cantidad']} cargado(s) · {alerta['tipos']} · Próximo vencimiento: {alerta['proximo_vto'] or '-'}",
                tipo="syh_matafuegos",
                autor="Sistema",
                link="/admin/syh",
            )
        nuevas_alertas.append(alerta)

    return nuevas_alertas


def sync_alertas_habilitaciones(prev_map=None):
    prev_map = prev_map or {}
    items = [_enrich_habilitacion(h) for h in load_habilitaciones().get("habilitaciones", [])]
    nuevas_alertas = []
    for h in items:
        estado = h.get("estado")
        if estado not in ("por_vencer", "vencida"):
            continue
        suc_num = h.get("sucursal_num") or (h.get("sucursal", "").replace("Sucursal ", "").strip())
        aid = f"habilitacion:{h.get('id') or suc_num}:{estado}"
        alerta = {
            "id": aid,
            "tipo": "habilitacion",
            "sucursal_num": suc_num,
            "sucursal": h.get("sucursal", ""),
            "estado": "Vencida" if estado == "vencida" else "Próximo a vencer",
            "proximo_vto": h.get("fecha_vencimiento", ""),
            "tipos": h.get("numero_cert", "") or h.get("municipio", "") or "Habilitación",
            "cantidad": 1,
            "destinatarios": ["Agustín", "Patricia", f"Sucursal {suc_num}"],
            "updated_at": datetime.datetime.now().isoformat(),
        }
        dias = None
        try:
            dias = (datetime.date.fromisoformat((h.get("fecha_vencimiento") or "")[:10]) - datetime.date.today()).days
        except (ValueError, TypeError):
            pass
        if aid not in prev_map:
            detalle_extra = f"Vence el {alerta['proximo_vto'] or '-'}"
            if dias is not None and dias >= 0:
                detalle_extra += f" ({dias} día(s))"
            agregar_notif_admin(
                f"🚨 Habilitación {alerta['estado'].lower()} - Sucursal {suc_num}",
                f"{alerta['tipos']} · {detalle_extra}\nRevisar con Patricia y sucursal.",
                tipo="syh_habilitacion",
                autor="Sistema",
                link="/admin/syh",
            )
        elif prev_map[aid].get("proximo_vto") != alerta.get("proximo_vto") or prev_map[aid].get("tipos") != alerta.get("tipos"):
            agregar_notif_admin(
                f"🔄 Actualización habilitación - Sucursal {suc_num}",
                f"Estado: {alerta['estado']} · {alerta['tipos']} · Vencimiento: {alerta['proximo_vto'] or '-'}",
                tipo="syh_habilitacion",
                autor="Sistema",
                link="/admin/syh",
            )
        nuevas_alertas.append(alerta)
    return nuevas_alertas


def sync_alertas_syh():
    data = load_alertas_syh()
    prev_map = {a.get("id"): a for a in data.get("alertas", [])}
    alertas = []
    alertas.extend(sync_alertas_matafuegos())
    alertas.extend(sync_alertas_habilitaciones(prev_map))
    data["alertas"] = alertas
    save_alertas_syh(data)
    if alertas:
        suc_lista = ", ".join(sorted({str(a.get("sucursal_num", "?")) for a in alertas}))
        _telegram_notify(
            f"⚠️ Tecman — {len(alertas)} alerta(s) de matafuegos pendientes de enviar\n"
            f"Sucursales: {suc_lista}\n\n"
            f"Entrá al panel admin → S&H → para revisar y enviar los mails."
        )
    return alertas

def load_alertas_syh_dispatch():
    if USE_DB:
        return _db_cfg_get("alertas_syh_dispatch", {"sent": {}})
    if ALERTAS_SYH_DISPATCH_FILE.exists():
        try:
            return json.loads(ALERTAS_SYH_DISPATCH_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {"sent": {}}

def save_alertas_syh_dispatch(data):
    if USE_DB:
        _db_cfg_set("alertas_syh_dispatch", data)
    _atomic_write(ALERTAS_SYH_DISPATCH_FILE, data)

def _fila_alerta(a):
    color = "#fee2e2" if a.get("estado") == "Vencidos" else "#fef3c7"
    return (
        f"<tr style='background:{color};'>"
        f"<td style='padding:8px;border-bottom:1px solid #eee;font-weight:700;'>Suc. {a.get('sucursal_num')}</td>"
        f"<td style='padding:8px;border-bottom:1px solid #eee;'>{a.get('estado')}</td>"
        f"<td style='padding:8px;border-bottom:1px solid #eee;'>{a.get('proximo_vto') or '-'}</td>"
        f"<td style='padding:8px;border-bottom:1px solid #eee;'>{a.get('tipos') or '-'}</td>"
        f"<td style='padding:8px;border-bottom:1px solid #eee;'>{a.get('cantidad') or 0}</td>"
        f"</tr>"
    )

def _tabla_alertas(filas_html):
    return (
        "<table style='width:100%;border-collapse:collapse;'>"
        "<tr>"
        "<th align='left' style='padding:8px;border-bottom:2px solid #ddd;'>Sucursal</th>"
        "<th align='left' style='padding:8px;border-bottom:2px solid #ddd;'>Estado</th>"
        "<th align='left' style='padding:8px;border-bottom:2px solid #ddd;'>Próx. vencimiento</th>"
        "<th align='left' style='padding:8px;border-bottom:2px solid #ddd;'>Tipos</th>"
        "<th align='left' style='padding:8px;border-bottom:2px solid #ddd;'>Cantidad</th>"
        "</tr>"
        + filas_html +
        "</table>"
    )

def _telegram_notify(mensaje):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        import urllib.request
        import urllib.parse
        data = urllib.parse.urlencode({"chat_id": TELEGRAM_CHAT_ID, "text": mensaje}).encode()
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage", data=data
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass


def _smtp_send(to, subject, html, attachment_path=None, attachment_name=None):
    if not GMAIL_USER or not GMAIL_APP_PASSWORD:
        raise RuntimeError("GMAIL_USER y GMAIL_APP_PASSWORD no configurados")
    msg = MIMEMultipart()
    msg["From"] = GMAIL_USER
    msg["To"] = to if isinstance(to, str) else ", ".join(to)
    msg["Subject"] = subject
    msg.attach(MIMEText(html, "html"))
    if attachment_path and Path(attachment_path).exists():
        with open(attachment_path, "rb") as f:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f'attachment; filename="{attachment_name or Path(attachment_path).name}"')
        msg.attach(part)
    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx) as server:
        server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        recipients = [to] if isinstance(to, str) else to
        server.sendmail(GMAIL_USER, recipients, msg.as_bytes())


def enviar_alertas_matafuegos_email():
    alertas = load_alertas_syh().get("alertas", [])
    alertas_mat = [a for a in alertas if a.get("tipo_alerta") != "habilitacion"]
    if not alertas_mat:
        return {"sent": 0, "reason": "no_alertas"}

    dispatch = load_alertas_syh_dispatch()
    sent_map = dispatch.setdefault("sent", {})
    pendientes = []
    for a in alertas_mat:
        aid = a.get("id")
        stamp = f"{a.get('estado')}|{a.get('proximo_vto')}|{a.get('cantidad')}|{a.get('tipos')}"
        if sent_map.get(aid) != stamp:
            pendientes.append((a, stamp))

    if not pendientes:
        return {"sent": 0, "reason": "sin_cambios"}

    try:
        from collections import defaultdict
        sent_count = 0

        por_sucursal = defaultdict(list)
        for a, stamp in pendientes:
            por_sucursal[str(a.get("sucursal_num", "")).zfill(3)].append((a, stamp))

        for suc_num, items in por_sucursal.items():
            suc_email = SUCURSAL_EMAILS.get(suc_num)
            if not suc_email:
                continue
            filas = "".join(_fila_alerta(a) for a, _ in items)
            html = f"""
            <div style='font-family:Arial,sans-serif;max-width:700px;margin:0 auto;'>
              <h2 style='color:#dc2626;'>Alerta de matafuegos - Sucursal {suc_num}</h2>
              <p>Se detectaron matafuegos con vencimiento próximo o vencidos en su sucursal. Por favor coordinen con el proveedor para regularizar la situación.</p>
              {_tabla_alertas(filas)}
              <p style='margin-top:16px;color:#6b7280;font-size:13px;'>Ante cualquier consulta, contactarse con el equipo de mantenimiento.</p>
            </div>
            """
            _smtp_send(suc_email, f"Tecman - Alerta matafuegos Suc. {suc_num}", html)
            sent_count += 1

        filas_todas = "".join(_fila_alerta(a) for a, _ in pendientes)
        html_patricia = f"""
        <div style='font-family:Arial,sans-serif;max-width:700px;margin:0 auto;'>
          <h2 style='color:#dc2626;'>Resumen alertas matafuegos - Tecman</h2>
          <p>{len(pendientes)} alerta(s) nuevas o actualizadas en {len(por_sucursal)} sucursal(es). Cada sucursal ya fue notificada.</p>
          {_tabla_alertas(filas_todas)}
          <p style='margin-top:16px;color:#6b7280;font-size:13px;'>Generado automáticamente por Tecman.</p>
        </div>
        """
        _smtp_send(PATRICIA_EMAIL, f"Tecman - Resumen alertas matafuegos ({len(pendientes)} alertas, {len(por_sucursal)} sucursales)", html_patricia)

        for a, stamp in pendientes:
            sent_map[a.get("id")] = stamp
        save_alertas_syh_dispatch(dispatch)
        return {"sent": sent_count, "reason": "ok"}
    except Exception as e:
        return {"sent": 0, "reason": f"error: {e}"}

def _enviar_requisicion_compras(ticket, req_numero, archivo_path=None, archivo_nombre=None):
    try:
        suc = ticket.get("sucursal", "-")
        subcat = ticket.get("subcategoria", "-")
        zona = ticket.get("zona_afectada", "-")
        prov = ticket.get("proveedor_presupuesto", "-")
        desc = ticket.get("descripcion", "-")
        montos = "".join(
            f"<tr><td style='padding:6px 10px;border-bottom:1px solid #eee;'>{p.get('proveedor') or prov}</td>"
            f"<td style='padding:6px 10px;border-bottom:1px solid #eee;'>${p.get('monto') or '-'}</td>"
            f"<td style='padding:6px 10px;border-bottom:1px solid #eee;'>{p.get('detalle') or '-'}</td></tr>"
            for p in (ticket.get("presupuestos") or [])
        )
        html = f"""
        <div style='font-family:Arial,sans-serif;max-width:680px;margin:0 auto;color:#1a1a2e;'>
          <h2 style='color:#0f766e;'>Requisición lista para procesar — Tecman</h2>
          <p>Rita cargó la requisición <strong>#{req_numero}</strong> para el siguiente presupuesto aprobado:</p>
          <table style='width:100%;border-collapse:collapse;margin-bottom:16px;'>
            <tr><td style='padding:8px 12px;background:#f0fdfa;font-weight:700;width:160px;'>Sucursal</td><td style='padding:8px 12px;background:#f8fafc;'>{suc}</td></tr>
            <tr><td style='padding:8px 12px;background:#f0fdfa;font-weight:700;'>Trabajo</td><td style='padding:8px 12px;background:#f8fafc;'>{subcat}</td></tr>
            <tr><td style='padding:8px 12px;background:#f0fdfa;font-weight:700;'>Zona</td><td style='padding:8px 12px;background:#f8fafc;'>{zona}</td></tr>
            <tr><td style='padding:8px 12px;background:#f0fdfa;font-weight:700;'>Proveedor</td><td style='padding:8px 12px;background:#f8fafc;'>{prov}</td></tr>
            <tr><td style='padding:8px 12px;background:#f0fdfa;font-weight:700;'>Descripción</td><td style='padding:8px 12px;background:#f8fafc;'>{desc}</td></tr>
          </table>
          {"<table style='width:100%;border-collapse:collapse;margin-bottom:16px;'><tr><th align='left' style='padding:6px 10px;border-bottom:2px solid #ddd;'>Proveedor</th><th align='left' style='padding:6px 10px;border-bottom:2px solid #ddd;'>Monto</th><th align='left' style='padding:6px 10px;border-bottom:2px solid #ddd;'>Detalle</th></tr>" + montos + "</table>" if montos else ""}
          <p style='color:#6b7280;font-size:13px;'>Ticket #{ticket.get("id")} — generado automáticamente por Tecman</p>
        </div>
        """

        _smtp_send(COMPRAS_EMAIL, f"Requisición #{req_numero} — {suc} ({subcat})", html,
                   attachment_path=archivo_path, attachment_name=archivo_nombre)
        return True
    except Exception as e:
        return False


def load_vehiculos_equipo():
    if USE_DB:
        return {"vehiculos": _db_list(VehiculoDB)}
    if VEHICULOS_FILE.exists():
        try:
            return json.loads(VEHICULOS_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {"vehiculos": []}

def save_vehiculos_equipo(data):
    if USE_DB:
        _db_replace(VehiculoDB, data.get("vehiculos", []))
    _atomic_write(VEHICULOS_FILE, data)

def load_permisos():
    if USE_DB:
        return {"permisos": _db_list(PermisoDB)}
    if PERMISOS_FILE.exists():
        try:
            return json.loads(PERMISOS_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {"permisos": []}

def save_permisos(data):
    if USE_DB:
        _db_replace(PermisoDB, data.get("permisos", []))
    _atomic_write(PERMISOS_FILE, data)

def load_presupuestos():
    if USE_DB:
        return {"presupuestos": _db_list(PresupuestoDB)}
    if PRESUPUESTOS_FILE.exists():
        try:
            return json.loads(PRESUPUESTOS_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {"presupuestos": []}

def save_presupuestos(data):
    if USE_DB:
        _db_replace(PresupuestoDB, data.get("presupuestos", []))
    _atomic_write(PRESUPUESTOS_FILE, data)

def load_ceyh_retiros():
    if USE_DB:
        return {"retiros": _db_list(CeyhRetiroDB)}
    if CEYH_RETIROS_FILE.exists():
        try:
            return json.loads(CEYH_RETIROS_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {"retiros": []}

def save_ceyh_retiros(data):
    if USE_DB:
        _db_replace(CeyhRetiroDB, data.get("retiros", []))
    _atomic_write(CEYH_RETIROS_FILE, data)

def load_ceyh_jornadas():
    if USE_DB:
        return {"jornadas": _db_list(CeyhJornadaDB)}
    if CEYH_JORNADAS_FILE.exists():
        try:
            return json.loads(CEYH_JORNADAS_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {"jornadas": []}

def save_ceyh_jornadas(data):
    if USE_DB:
        _db_replace(CeyhJornadaDB, data.get("jornadas", []))
    _atomic_write(CEYH_JORNADAS_FILE, data)

def es_ticket_ceyh(ticket):
    return ticket.get("asignado") == "CEYH" or ticket.get("asignado_proveedor") == "CEYH" or ticket.get("proveedor_nombre") == "CEYH" or ticket.get("derivado_desde") == "CEYH"

def _normalize_ceyh_ticket(ticket):
    ticket.setdefault("requiere_materiales", False)
    ticket.setdefault("estado_materiales", "No requiere")
    ticket.setdefault("requiere_retiro_central", False)
    ticket.setdefault("estado_retiro", "No requiere")
    ticket.setdefault("cuadrilla_ceyh", "")
    ticket.setdefault("camioneta_ceyh", "")
    ticket.setdefault("ultima_novedad_operativa", "")
    ticket.setdefault("proxima_accion", "")
    ticket.setdefault("fecha_objetivo", "")
    ticket.setdefault("estado_operativo_ceyh", "Pendiente")
    return ticket

def _expand_permisos_para_sucursales(items):
    expanded = []
    for p in items:
        destinos = p.get("sucursales") or []
        if destinos:
            for d in destinos:
                x = dict(p)
                x["sucursal"] = d.get("sucursal", "")
                x["sucursal_num"] = d.get("sucursal_num", "")
                x["fao_estado"] = d.get("fao_estado", p.get("fao_estado", "Pendiente"))
                x["fao_fecha"] = d.get("fao_fecha", "")
                x["destino_id"] = d.get("id", "")
                expanded.append(x)
        else:
            x = dict(p)
            x.setdefault("fao_estado", p.get("fao_estado", "Pendiente"))
            expanded.append(x)
    return expanded

def load_alertas_syh():
    if USE_DB:
        return {"alertas": _db_list(AlertaSyhDB)}
    if ALERTAS_SYH_FILE.exists():
        try:
            return json.loads(ALERTAS_SYH_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {"alertas": []}

def save_alertas_syh(data):
    if USE_DB:
        _db_replace(AlertaSyhDB, data.get("alertas", []))
    _atomic_write(ALERTAS_SYH_FILE, data)

def _estado_doc_vehiculo(fecha):
    if not fecha:
        return "sin_dato"
    try:
        venc = datetime.date.fromisoformat(str(fecha)[:10])
    except (TypeError, ValueError):
        return "sin_dato"
    hoy = datetime.date.today()
    if venc < hoy:
        return "vencido"
    if venc <= hoy + datetime.timedelta(days=30):
        return "proximo"
    return "ok"

def _enrich_vehiculo(v):
    x = dict(v)
    x["estado_seguro"] = _estado_doc_vehiculo(x.get("seguro_vencimiento"))
    x["estado_vtv"] = _estado_doc_vehiculo(x.get("vtv_vencimiento"))
    return x

HABILITACION_EXTENSIONES = {".pdf", ".jpg", ".jpeg", ".png"}

def _calc_estado_habilitacion(fecha_vencimiento, hoy=None):
    """Calcula el estado segun la fecha de vencimiento (formato YYYY-MM-DD)."""
    if not fecha_vencimiento:
        return "sin_dato"
    try:
        venc = datetime.date.fromisoformat(fecha_vencimiento[:10])
    except (ValueError, TypeError):
        return "sin_dato"
    hoy = hoy or datetime.date.today()
    if venc < hoy:
        return "vencida"
    if (venc - hoy).days <= 90:
        return "por_vencer"
    return "vigente"

def _enrich_habilitacion(h):
    """Agrega estado calculado al dict de habilitacion (no muta el original)."""
    out = dict(h)
    out["estado"] = _calc_estado_habilitacion(h.get("fecha_vencimiento", ""))
    return out

ESTADO_HAB_ORDEN = {"vencida": 0, "por_vencer": 1, "vigente": 2, "sin_dato": 3}

def _next_guia_numero():
    data = _load_guias_counter()
    try:
        ultimo = int(data.get("ultimo", 87889))
    except (TypeError, ValueError):
        ultimo = 87889
    ultimo += 1
    data["ultimo"] = ultimo
    _save_guias_counter(data)
    return ultimo

def _formatear_guia_numero(n):
    """Formato de guia interna: 9902-XXXXXXXX (8 digitos)."""
    try:
        return f"9902-{int(n):08d}"
    except (TypeError, ValueError):
        s = str(n or "").strip()
        return s or "9902-00000000"

def _get_precio_historico(item_key, hasta=None):
    """Retorna el precio unitario del ultimo ingreso de un item antes de 'hasta'.
    Si no hay ingresos registrados, retorna None."""
    movimientos = load_movimientos()
    ingresos = [
        m for m in movimientos.get("movimientos", [])
        if m.get("item") == item_key
        and m.get("tipo") == "ingreso"
        and m.get("precio_unitario", 0)
    ]
    if hasta:
        ingresos = [m for m in ingresos if m.get("fecha", "") <= hasta]
    if not ingresos:
        return None
    # FIFO: ordenar por fecha ascendente, tomar el mas antiguo (primera compra)
    ingresos.sort(key=lambda m: m.get("fecha", ""))
    return float(ingresos[0].get("precio_unitario", 0))


def registrar_movimiento(item, tipo, cantidad, sucursal="", ticket_id=None, nota="", monto_imputado=None, precio_unitario=None, area=None, envio_id=None, lotes_origen=None, numero_comprobante_origen=None, proveedor_origen=None, sin_trazabilidad_fifo=None):
    """Registra un movimiento de stock (ingreso o egreso)."""
    if not item or not tipo or not cantidad:
        return
    data = load_movimientos()
    mov = {
        "id": uuid.uuid4().hex[:12],
        "item": item,
        "tipo": tipo,
        "cantidad": int(cantidad),
        "fecha": datetime.datetime.now().isoformat(),
        "sucursal": sucursal or "",
        "ticket_id": ticket_id,
        "nota": nota or "",
    }
    if monto_imputado is not None:
        mov["monto_imputado"] = float(monto_imputado)
    if precio_unitario is not None:
        mov["precio_unitario"] = float(precio_unitario)
    if area:
        mov["area"] = area
    if envio_id:
        mov["envio_id"] = envio_id
    if lotes_origen:
        mov["lotes_origen"] = lotes_origen
    if numero_comprobante_origen:
        mov["numero_comprobante_origen"] = numero_comprobante_origen
    if proveedor_origen:
        mov["proveedor_origen"] = proveedor_origen
    if sin_trazabilidad_fifo:
        mov["sin_trazabilidad_fifo"] = True
    data.setdefault("movimientos", []).append(mov)
    save_movimientos(data)

# Sucursal login: each sucursal has a unique password
_SUC_PREFIX = os.environ.get("SUCURSAL_PASSWORD_PREFIX", "mto")

SUCURSAL_USERS = {}
for suc in SUCURSALES:
    # Extract number or key from name
    if "Sucursal" in suc:
        num = suc.replace("Sucursal ", "")
        SUCURSAL_USERS[f"suc{num}"] = {"password": f"{_SUC_PREFIX}{num}", "sucursal": suc}
    elif suc == "Central - Dabra":
        SUCURSAL_USERS["central"] = {"password": f"{_SUC_PREFIX}central", "sucursal": suc}
    elif suc == "Garin":
        SUCURSAL_USERS["garin"] = {"password": f"{_SUC_PREFIX}garin", "sucursal": suc}

# Auto-assignment rules
ASIGNACION_DEFAULT = "Agustín Brahim"

# Sucursales por zona para asignación automática
SUCS_CORDOBA = {"076","078","123","124","203","215","224","233"}
SUCS_NOA = {"120","126","128","135","139","146","158","173","191","193","212","229","230","234","235"}
SUCS_MENDOZA = {"128","132","145","206","207","236"}
SUCS_SANJUAN = {"159","172"}

_PROVEEDOR_PWD = os.environ.get("PROVEEDOR_PASSWORD", "prov2026")

# Proveedor login
PROVEEDOR_USERS = {
    "ceyh": {"password": _PROVEEDOR_PWD, "nombre": "CEYH"},
    "gustavo": {"password": _PROVEEDOR_PWD, "nombre": "Gustavo Avellaneda"},
    "fuga": {"password": _PROVEEDOR_PWD, "nombre": "Julio Fuga (JRF)"},
    "ismael": {"password": _PROVEEDOR_PWD, "nombre": "Ismael Allende (JRF)"},
    "escalmeca": {"password": _PROVEEDOR_PWD, "nombre": "Escalmeca / Mauricio"},
    "adriel": {"password": _PROVEEDOR_PWD, "nombre": "Adriel (Pintor)"},
    "oscar": {"password": _PROVEEDOR_PWD, "nombre": "Oscar San Juan"},
    "jose": {"password": _PROVEEDOR_PWD, "nombre": "Jose Sanchez"},
    "blanco": {"password": _PROVEEDOR_PWD, "nombre": "Gustavo Blanco"},
    "nestor": {"password": _PROVEEDOR_PWD, "nombre": "Nestor Raul Diaz"},
    "federico": {"password": _PROVEEDOR_PWD, "nombre": "Federico Confort"},
    "javier": {"password": _PROVEEDOR_PWD, "nombre": "Javier"},
    "nicolas": {"password": _PROVEEDOR_PWD, "nombre": "Nicolas Audio"},
    "frattini": {"password": _PROVEEDOR_PWD, "nombre": "Cesar Frattini (No Bugs)"},
    "polaris": {"password": _PROVEEDOR_PWD, "nombre": "Polaris"},
    "astronovo": {"password": _PROVEEDOR_PWD, "nombre": "Astronovo"},
    "geronimo": {"password": _PROVEEDOR_PWD, "nombre": "Geronimo - Leo"},
    "croacia": {"password": _PROVEEDOR_PWD, "nombre": "Croacia"},
    "microglobal": {"password": _PROVEEDOR_PWD, "nombre": "Martin Microglobal"},
}

# Proveedores database
PROVEEDORES = [
    {"nombre": "Personal Mto. (camionetas propias)", "zona": "AMBA", "tipo": "General", "tel": "-", "sucursales": ["011","014","023","028","035","036","043","051","052","053","054","058","065","077","080","082","083","102","111","141","147","148","165","167","170","171","176","177","184","185","186","188","190","192","194","196","198","202","208","209","211","214","217","222","228"], "monto": "Recurso propio (2 camionetas, 2 tecnicos FT, 1 PT)", "incluye": "Mantenimiento general CABA/GBA", "no_incluye": "-"},
    {"nombre": "CEYH", "zona": "AMBA", "tipo": "General + AA", "tel": "11 3205-3759", "contacto": "Gaston", "fijo": True, "sucursales": ["011","014","020","023","028","035","036","043","049","051","052","053","054","058","065","077","080","082","083","092","102","111","121","125","141","142","147","148","156","157","165","167","170","171","176","177","183","184","185","186","187","188","190","192","194","195","196","198","199","200","202","204","208","209","211","213","214","216","219","221","222","228","232","234","238"], "monto": "$30.000.000 + IVA/mes", "incluye": "3 moviles (2 AA + 1 gral), 9hs L-V, 2 tecnicos por movil, mano de obra, supervision, vehiculo, herramientas", "no_incluye": "Materiales, consumibles. Fuera de horario se cobra aparte (min 3hs por movil)"},
    {"nombre": "Martin Microglobal", "zona": "AMBA", "tipo": "General", "tel": "11 5410-6488", "contacto": "Martin", "fijo": False, "sucursales": ["011","023","036","077","147","176","177","183","186","198","209","211","213","222","223","234"]},
    {"nombre": "Angel JYS", "zona": "AMBA", "tipo": "General", "tel": "113560-9316", "sucursales": ["Zona Norte AMBA"]},
    {"nombre": "Jorge (Limpieza vidrios)", "zona": "AMBA", "tipo": "Limpieza", "tel": "115182-7823", "sucursales": ["AMBA general"]},
    {"nombre": "Polaris", "zona": "AMBA", "tipo": "General", "tel": "11 6527-7128", "contacto": "Lucas", "fijo": True, "sucursales": ["171","183","184"]},
    {"nombre": "Astronovo AM", "zona": "AMBA", "tipo": "General", "tel": "11 5182-3968", "contacto": "Dylan", "fijo": True, "sucursales": ["186"]},
    {"nombre": "Astronovo HV", "zona": "AMBA", "tipo": "General", "tel": "11 3813-9215", "contacto": "Horacio", "fijo": True, "sucursales": ["176"]},
    {"nombre": "Escalmeca / Mauricio", "zona": "AMBA", "tipo": "Escaleras mecanicas", "tel": "115308-9834", "sucursales": ["183","184","186"], "monto": "$688.000 + IVA/mes", "incluye": "Mantenimiento preventivo de 8 escaleras mecanicas en 3 sucursales, lubricacion, engrase, limpieza, desarme parcial", "no_incluye": "-"},
    {"nombre": "L&G (Geronimo)", "zona": "AMBA", "tipo": "Tecnicos", "tel": "54 9 2236 69-2804", "contacto": "Geronimo", "fijo": False, "sucursales": ["092","217","239","240"]},
    {"nombre": "Nicolas Audio", "zona": "Nacional", "tipo": "Audio", "tel": "-", "sucursales": ["036","049","053","065","077","083","091","092","125","127","128","141","148","156","165","166","167","176","177","183","186","194","200","202","210","211","213","216","226"]},
    {"nombre": "Gustavo Avellaneda", "zona": "Cordoba", "tipo": "General", "tel": "0351-320-1198", "sucursales": ["076","078","123","124","203","215","224","233"], "monto": "$1.800.000/mes", "incluye": "Limpieza canaletas/techos, filtros AA, destapes, plomeria menor, albañileria menor, pintura menor, luminarias, cerraduras, arranque semanal generadores, mantenimiento AA planificado", "no_incluye": "Combustible, pintura grande, zingueria, techos, albañileria mayor"},
    {"nombre": "Adriel (Pintor)", "zona": "Cordoba", "tipo": "Pintura", "tel": "351-860-2101", "sucursales": ["076","078","123","124","203","215","233"]},
    {"nombre": "Julio Fuga (JRF)", "zona": "NOA", "tipo": "Electrico + AA + Gral", "tel": "0381-454-5659", "sucursales": ["120","126","128","132","135","139","145","146","158","173","191","193","206","207","212","229","230","234","235","236"], "monto": "$2.050.000 + IVA/mes + San Luis/Mendoza $1.200.000", "incluye": "Mto electrico preventivo (luminarias, tableros, bornes, termicas), mto AA (filtros, evaporadora, condensadora, desagues, plaquetas), 3 personas/visita, 2 urgencias/mes/suc", "no_incluye": "-"},
    {"nombre": "Oscar San Juan", "zona": "San Juan", "tipo": "General", "tel": "0264-498-5365", "sucursales": ["159","172"]},
    {"nombre": "Jose Sanchez", "zona": "San Juan", "tipo": "General", "tel": "0264-504-1961", "sucursales": ["159","172"]},
    {"nombre": "Majo / Nivelar Construcciones", "zona": "Chaco/Corrientes", "tipo": "General / Construccion", "tel": "54 9 364 430-2787", "contacto": "Maria Jose", "fijo": False, "sucursales": ["220","224"]},
    {"nombre": "Nestor Raul Diaz", "zona": "Neuquen", "tipo": "General", "tel": "299-418-7955", "sucursales": ["133"]},
    {"nombre": "Federico Confort", "zona": "Parana", "tipo": "General", "tel": "299-418-7955", "contacto": "Federico", "fijo": True, "sucursales": ["178","210"]},
    {"nombre": "Javier", "zona": "Santa Fe", "tipo": "General", "tel": "342-478-0031", "sucursales": ["226"]},
    {"nombre": "Cesar Frattini (No Bugs)", "zona": "AMBA", "tipo": "Fumigaciones", "tel": "114474-9457", "sucursales": ["165","183","200","208","209","211","213","214","221","222"], "monto": "Por servicio", "incluye": "Fumigacion, urgencias bonificadas", "no_incluye": "-", "mostrar_sucursal": False},
    {"nombre": "Gerardo Goog", "zona": "AMBA", "tipo": "Fumigaciones", "tel": "115851-5565", "sucursales": ["052","167","187"], "mostrar_sucursal": False},
    {"nombre": "Pablo Norsuply", "zona": "AMBA", "tipo": "Insumos", "tel": "115923-5320", "sucursales": ["AMBA general"]},
    {"nombre": "Croacia", "zona": "AMBA", "tipo": "Urgencias persianas", "tel": "11 3663-6408", "contacto": "Raquel", "fijo": False, "sucursales": ["AMBA general"]},
    {"nombre": "Home Pro", "zona": "AMBA", "tipo": "General", "tel": "11 4416-3911", "contacto": "Nicolas", "fijo": False, "sucursales": ["AMBA eventual"]},
    {"nombre": "Conex", "zona": "Neuquen", "tipo": "General", "tel": "54 9 2995 57-5495", "contacto": "Rodrigo", "fijo": False, "sucursales": ["160","233","133","134","231"]},
    {"nombre": "Atila Generaciones", "zona": "AMBA", "tipo": "Grupos electrogenos", "tel": "115318-3306", "contacto": "Waldo", "fijo": True, "sucursales": ["195","208","211","Garin"]},
    {"nombre": "Layerenza Cortinas", "zona": "Cordoba", "tipo": "Cortinas", "tel": "351-545-1732", "fijo": False, "sucursales": ["076","078","123","124","203","215","233"]},
    # --- Proveedores de fumigacion por sucursal ---
    {"nombre": "Cesar Ricardo Fratini", "zona": "Nacional", "tipo": "Fumigaciones", "tel": "-", "fijo": False, "sucursales": ["014","020","028","035","036","049","053","054","102","111","121","125","141","147","148","156","157","165","170","176","177","183","184","185","186","190","192","196","198","199","200","202","208","213","214","219","221","228","234","237","238"], "mostrar_sucursal": False},
    {"nombre": "INGAM Control de Plagas SRL", "zona": "Nacional", "tipo": "Fumigaciones", "tel": "-", "contacto": "Fernando", "fijo": False, "sucursales": ["011","058","065","077","080","082","083","142","173","188","191","194","195","209","211","216","222","230"], "mostrar_sucursal": False},
    {"nombre": "David Esteban Medina", "zona": "Cordoba", "tipo": "Fumigaciones", "tel": "-", "fijo": False, "sucursales": ["076","078","123","124","203","215","233"], "mostrar_sucursal": False},
    {"nombre": "Diprogom", "zona": "AMBA", "tipo": "Matafuegos", "tel": "-", "fijo": False, "sucursales": ["222"]},
    {"nombre": "Gerardo Osvaldo Gonzalez", "zona": "AMBA", "tipo": "Fumigaciones", "tel": "-", "fijo": False, "sucursales": ["052","167","187"], "mostrar_sucursal": False},
    {"nombre": "Vasquez Marisel Vicenta", "zona": "NOA", "tipo": "Fumigaciones", "tel": "-", "fijo": False, "sucursales": ["126","139","193"], "mostrar_sucursal": False},
    {"nombre": "Lassna SRL", "zona": "AMBA", "tipo": "Fumigaciones", "tel": "-", "fijo": False, "sucursales": ["051","171"], "mostrar_sucursal": False},
    {"nombre": "Sindel Siscobio", "zona": "NOA", "tipo": "Fumigaciones", "tel": "-", "fijo": False, "sucursales": ["146","158"], "mostrar_sucursal": False},
    {"nombre": "Contreras Mauricio Sergio", "zona": "Cuyo", "tipo": "Fumigaciones", "tel": "-", "fijo": False, "sucursales": ["159","172"], "mostrar_sucursal": False},
    {"nombre": "Manggini Pablo y Ulises", "zona": "AMBA", "tipo": "Fumigaciones", "tel": "-", "fijo": False, "sucursales": ["043","204"], "mostrar_sucursal": False},
    {"nombre": "Municipalidad de Moreno", "zona": "AMBA", "tipo": "Fumigaciones", "tel": "-", "fijo": False, "sucursales": ["023","232"], "mostrar_sucursal": False},
    {"nombre": "Jorge Alejandro Gardel", "zona": "NOA", "tipo": "Fumigaciones", "tel": "-", "fijo": False, "sucursales": ["120","212"], "mostrar_sucursal": False},
    {"nombre": "Imhoff Fernando Alberto", "zona": "Litoral", "tipo": "Fumigaciones", "tel": "-", "fijo": False, "sucursales": ["114","226"], "mostrar_sucursal": False},
    {"nombre": "Felix Raul Millan", "zona": "Cuyo", "tipo": "Fumigaciones", "tel": "-", "fijo": False, "sucursales": ["145"], "mostrar_sucursal": False},
    {"nombre": "Nazareno Marchilli", "zona": "AMBA", "tipo": "Fumigaciones", "tel": "-", "fijo": False, "sucursales": ["116"], "mostrar_sucursal": False},
    {"nombre": "Comservar SRL", "zona": "Cuyo", "tipo": "Fumigaciones", "tel": "-", "fijo": False, "sucursales": ["207"], "mostrar_sucursal": False},
    {"nombre": "Rabincho SRL", "zona": "NEA", "tipo": "Fumigaciones", "tel": "-", "fijo": False, "sucursales": ["220"], "mostrar_sucursal": False},
    {"nombre": "Perez Bobadilla Nicolas", "zona": "NEA", "tipo": "Fumigaciones", "tel": "-", "fijo": False, "sucursales": ["224"], "mostrar_sucursal": False},
    {"nombre": "Marcelo Domingo Pedregal", "zona": "NOA", "tipo": "Fumigaciones", "tel": "-", "fijo": False, "sucursales": ["229"], "mostrar_sucursal": False},
    {"nombre": "ULT SRL", "zona": "NOA", "tipo": "Fumigaciones", "tel": "-", "fijo": False, "sucursales": ["235"], "mostrar_sucursal": False},
    # --- Nuevos proveedores fumigacion (actualizado 05/05/2026 - Rita Robles) ---
    {"nombre": "LANIDINI - VENA SALVADOR", "zona": "Litoral", "tipo": "Fumigaciones", "tel": "-", "fijo": False, "sucursales": ["127","166"], "mostrar_sucursal": False},
    {"nombre": "Castro Luna Dario", "zona": "Cuyo", "tipo": "Fumigaciones", "tel": "-", "fijo": False, "sucursales": ["128","206"], "mostrar_sucursal": False},
    {"nombre": "CHASQUI SRL", "zona": "Patagonia", "tipo": "Fumigaciones", "tel": "-", "fijo": False, "sucursales": ["133"], "mostrar_sucursal": False},
    {"nombre": "Mak Consulter S.R.L", "zona": "Cuyo", "tipo": "Fumigaciones", "tel": "-", "fijo": False, "sucursales": ["178"], "mostrar_sucursal": False},
    {"nombre": "FLR Control de Plagas (Isaurralde)", "zona": "Cuyo", "tipo": "Fumigaciones", "tel": "-", "fijo": False, "sucursales": ["210"], "mostrar_sucursal": False},
    {"nombre": "EXTER - Caviglia y Tellarini S.A.", "zona": "PBA Sur", "tipo": "Fumigaciones", "tel": "-", "fijo": False, "sucursales": ["217"], "mostrar_sucursal": False},
    {"nombre": "MIPSA SRL", "zona": "Patagonia", "tipo": "Fumigaciones", "tel": "-", "fijo": False, "sucursales": ["134","231"], "mostrar_sucursal": False},
    {"nombre": "La fumigación la realiza el shopping", "zona": "Nacional", "tipo": "Fumigaciones", "tel": "-", "fijo": False, "sucursales": ["132","160","236"], "mostrar_sucursal": False},
    {"nombre": "Solo bajo requerimiento puntual", "zona": "Nacional", "tipo": "Fumigaciones", "tel": "-", "fijo": False, "sucursales": ["091","092","205"], "mostrar_sucursal": False},
    {"nombre": "Sin servicio de fumigación", "zona": "Nacional", "tipo": "Fumigaciones", "tel": "-", "fijo": False, "sucursales": ["239","240","241"], "mostrar_sucursal": False},
]

ZONAS = sorted(set(p["zona"] for p in PROVEEDORES))


# --- Helpers ---

def _seed_data_dir():
    """Al arrancar en Render, copiar datos iniciales del repo al disco persistente si no existen."""
    repo_data = Path(__file__).parent / "data"
    for fname in ["tickets.json", "stock.json", "stock_movimientos.json", "comprobantes.json", "habilitaciones.json", "matafuegos.json", "syh.json", "permisos.json", "alertas_syh.json"]:
        dest = DATA_DIR / fname
        src = repo_data / fname
        if not dest.exists() and src.exists():
            shutil.copy2(src, dest)

_seed_data_dir()


def load_tickets():
    if USE_DB:
        return _db_list(TicketDB)
    if TICKETS_FILE.exists():
        try:
            return json.loads(TICKETS_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return []


def save_tickets(tickets):
    if USE_DB:
        _db_replace(TicketDB, tickets)
    _atomic_write(TICKETS_FILE, tickets)


def load_syh_gestiones():
    if USE_DB:
        return {"gestiones": _db_list(SyhGestionDB)}
    if SYH_GESTIONES_FILE.exists():
        try:
            return json.loads(SYH_GESTIONES_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {"gestiones": []}


def save_syh_gestiones(data):
    if USE_DB:
        _db_replace(SyhGestionDB, data.get("gestiones", []))
    _atomic_write(SYH_GESTIONES_FILE, data)


def auto_priority(categoria, subcategoria):
    if categoria == "Presupuestos":
        return 3
    # 1 Urgente: local no puede operar
    urgentes = {"Tablero", "Persianas"}
    if subcategoria in urgentes:
        return 1
    # 2 Alta: importante pero puede esperar 1-3 dias
    altas = {"Sin funcionamiento", "Reparacion", "Goteo", "Perdidas en canerias",
             "Perdidas en canillas", "Por alcantarillas", "Por azotea", "Por muros/humedad"}
    if subcategoria in altas or categoria == "Filtraciones" or categoria == "Aire Acondicionado":
        return 2
    # 3 Media: resolver en la semana
    medias = {"Luminarias", "Cambio", "General", "Solicitud de materiales", "Tablero",
              "Cableado", "Tomas", "Agua fria", "Agua caliente"}
    if subcategoria in medias or categoria == "Reparaciones" or categoria == "Materiales":
        return 3
    # 4 Baja: puede esperar
    return 4



def next_ticket_id(tickets):
    if not tickets:
        return 1
    return max(t["id"] for t in tickets) + 1


def get_proveedores_para_sucursal(suc_num):
    """Devuelve la lista de nombres de proveedores que cubren la sucursal.
    Prioriza PROVEEDORES_SUCURSAL (override manual) y si no hay, deriva
    del listado general PROVEEDORES segun el campo 'sucursales'."""
    try:
        from sucursales_data import PROVEEDORES_SUCURSAL
    except ImportError:
        PROVEEDORES_SUCURSAL = {}

    suc_num = str(suc_num).strip()
    override = PROVEEDORES_SUCURSAL.get(suc_num)
    if override:
        return list(override)

    nombres = []
    suc_num_sin_cero = suc_num.lstrip("0")
    for p in PROVEEDORES:
        for s in p.get("sucursales", []):
            if suc_num and (suc_num in s or (suc_num_sin_cero and suc_num_sin_cero in s)):
                if p["nombre"] not in nombres:
                    nombres.append(p["nombre"])
                break
    return nombres


def get_proveedor_abono_sucursal(suc_num):
    """Devuelve el nombre del primer proveedor 'fijo' (del abono) asignado
    a la sucursal, o None si no hay."""
    suc_num = str(suc_num).strip()
    suc_num_sin_cero = suc_num.lstrip("0")
    for p in PROVEEDORES:
        if not p.get("fijo"):
            continue
        for s in p.get("sucursales", []):
            if suc_num and (suc_num in s or (suc_num_sin_cero and suc_num_sin_cero in s)):
                return p["nombre"]
    return None


def es_sucursal_ceyh(suc_num):
    """Retorna True si la sucursal tiene CEYH como proveedor fijo."""
    suc_num = str(suc_num).strip()
    suc_num_sin_cero = suc_num.lstrip("0")
    for p in PROVEEDORES:
        if p.get("nombre") != "CEYH" or not p.get("fijo"):
            continue
        for s in p.get("sucursales", []):
            if suc_num == s or suc_num_sin_cero == s.lstrip("0"):
                return True
    return False


def auto_assign(subcategoria, sucursal="", categoria=""):
    # Extract sucursal number
    suc_num = sucursal.replace("Sucursal ", "").strip()

    subcat_l = (subcategoria or "").lower()
    categoria_l = (categoria or "").lower()
    es_grupo_electrogeno = any(k in subcat_l for k in ["grupo elect", "grupos elect", "electrogen", "generador"]) or any(k in categoria_l for k in ["grupo elect", "electrogen", "generador"])
    excluidos_equipo_ge = {"211", "196", "208", "garin"}
    es_amba = suc_num not in SUCS_CORDOBA and suc_num not in SUCS_NOA and suc_num not in SUCS_MENDOZA and suc_num not in SUCS_SANJUAN
    if es_grupo_electrogeno and es_amba and suc_num.lower() not in excluidos_equipo_ge:
        return "Equipo Central"

    # By category
    if subcategoria == "Luminarias":
        return "Jonatan"
    if categoria == "Materiales" or subcategoria == "Solicitud de materiales":
        return "Jonatan"
    if categoria == "Seguridad e Higiene":
        return "Patricia"
    if categoria == "Presupuestos":
        return ASIGNACION_DEFAULT
    if subcategoria in ("Reparacion", "Sin funcionamiento", "Goteo", "Limpieza interna de equipo") and "Aire" in subcategoria:
        # AA in AMBA goes to CEYH
        if suc_num not in SUCS_CORDOBA and suc_num not in SUCS_NOA and suc_num not in SUCS_MENDOZA and suc_num not in SUCS_SANJUAN:
            return "CEYH"

    # By zone / abono fijo
    if suc_num in SUCS_CORDOBA:
        return "Gustavo Avellaneda"
    if suc_num in SUCS_NOA:
        return "Julio Fuga (JRF)"
    proveedor_abono = get_proveedor_abono_sucursal(suc_num)
    if proveedor_abono:
        return proveedor_abono
    return ASIGNACION_DEFAULT


def any_session_required(f):
    """Permite acceso a cualquier portal autenticado (admin, suc, prov, equipo, compras, syh)."""
    @wraps(f)
    def decorated(*args, **kwargs):
        has_session = any(k in session for k in ("user", "suc_user", "prov_user", "equipo_user", "compras_user", "syh_user"))
        if not has_session:
            return render_template("error.html", mensaje="Acceso restringido."), 403
        return f(*args, **kwargs)
    return decorated


def login_required(f):
    """Permite acceso a cualquier usuario logueado (admin o tecnico)."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    """Solo permite acceso a usuarios con rol 'admin'."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("admin_login"))
        if session.get("rol") != "admin":
            return render_template("error.html", mensaje="Acceso restringido. Solo administradores."), 403
        return f(*args, **kwargs)
    return decorated


def suc_login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "suc_user" not in session:
            return redirect(url_for("suc_login"))
        return f(*args, **kwargs)
    return decorated


def compras_login_required(f):
    """Permite acceso solo a usuarios del portal de Compras (Laura)."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if "compras_user" not in session:
            return redirect(url_for("compras_login"))
        return f(*args, **kwargs)
    return decorated


def equipo_login_required(f):
    """Permite acceso al portal del Equipo Central.
    Acepta sesion de equipo (equipo_user) o admin con rol equipo_central
    o usuario 'equipo'."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if "equipo_user" in session:
            return f(*args, **kwargs)
        if session.get("user") == "equipo" or session.get("rol") == "equipo_central":
            return f(*args, **kwargs)
        return redirect(url_for("equipo_login"))
    return decorated


def _es_insumo_compras(item_key):
    """True si el item del stock pertenece a las categorias de Compras (Laura)."""
    from categories_data import INSUMOS_COMPRAS_CATEGORIAS
    if not item_key:
        return False
    item_str = str(item_key)
    return any(item_str.startswith(cat) for cat in INSUMOS_COMPRAS_CATEGORIAS)


def filtrar_stock_laura(stock):
    """Retorna dict {item: {cantidad, precio_unitario}} del stock central
    solo con los insumos que maneja Compras (Laura)."""
    central = (stock or {}).get("central", {}) or {}
    return {k: v for k, v in central.items() if _es_insumo_compras(k)}


# --- Routes: Sucursal login ---

@app.route("/")
def index():
    if "suc_user" in session:
        return redirect(url_for("suc_panel"))
    return render_template("index.html", sucursales=SUCURSALES)


@app.route("/login", methods=["GET", "POST"])
def suc_login():
    if request.method == "POST":
        user = request.form.get("usuario", "").lower().strip()
        pwd = request.form.get("password", "")
        if user in SUCURSAL_USERS and SUCURSAL_USERS[user]["password"] == pwd:
            session["suc_user"] = user
            session["suc_nombre"] = SUCURSAL_USERS[user]["sucursal"]
            return redirect(url_for("suc_panel"))
        flash("Usuario o contraseña incorrectos")
    return render_template("suc_login.html")


@app.route("/logout", methods=["GET", "POST"])
def suc_logout():
    session.pop("suc_user", None)
    session.pop("suc_nombre", None)
    return redirect(url_for("suc_login"))


@app.route("/mi-panel")
@suc_login_required
def suc_panel():
    tickets = load_tickets()
    mis_tickets = [t for t in tickets if t["sucursal"] == session["suc_nombre"]]
    mis_tickets.sort(key=lambda t: t["creado"], reverse=True)

    # Find providers for this sucursal
    suc_num = session["suc_nombre"].replace("Sucursal ", "").strip()
    mis_proveedores = []
    for p in PROVEEDORES:
        for s in p["sucursales"]:
            if s == suc_num or s == suc_num.lstrip("0"):
                if p.get("tipo") == "Fumigaciones" and p.get("mostrar_sucursal") is False:
                    continue
                mis_proveedores.append(p)
                break

    # Notifications
    notificaciones = []
    for t in mis_tickets:
        for n in t.get("notificaciones", []):
            notificaciones.append({"ticket_id": t["id"], **n})
    notificaciones.sort(key=lambda x: x.get("fecha", ""), reverse=True)

    # Stock recibido por esta sucursal
    stock = load_stock()
    mi_stock = stock.get("sucursales", {}).get(session["suc_nombre"], {}) or {}
    # Separar por tipo (insumos de compras vs mantenimiento)
    mi_stock_insumos = {k: v for k, v in mi_stock.items() if _es_insumo_compras(k)}
    mi_stock_manten = {k: v for k, v in mi_stock.items() if not _es_insumo_compras(k)}

    habs = [_enrich_habilitacion(h) for h in load_habilitaciones().get("habilitaciones", []) if h.get("sucursal") == session["suc_nombre"] or h.get("sucursal_num") == suc_num]
    habs.sort(key=lambda h: (ESTADO_HAB_ORDEN.get(h.get("estado"), 99), h.get("fecha_vencimiento", "9999-99-99") or "9999-99-99"))
    matafuegos = [_enrich_matafuego(m) for m in load_matafuegos().get("matafuegos", []) if m.get("sucursal") == session["suc_nombre"] or m.get("sucursal_num") == suc_num]
    matafuegos.sort(key=lambda m: (m.get("estado_calc") not in ("rechazado", "vencido"), m.get("fecha_control_calc", "9999-99-99") or "9999-99-99"))
    permisos = [p for p in _expand_permisos_para_sucursales(load_permisos().get("permisos", [])) if p.get("sucursal") == session["suc_nombre"] or p.get("sucursal_num") == suc_num]
    permisos.sort(key=lambda p: p.get("created_at", ""), reverse=True)
    estado_syh = load_syh().get(suc_num, {})

    return render_template(
        "suc_panel.html",
        tickets=mis_tickets,
        prioridades=PRIORIDADES,
        mis_proveedores=mis_proveedores,
        notificaciones=notificaciones,
        mi_stock_insumos=mi_stock_insumos,
        mi_stock_manten=mi_stock_manten,
        habilitaciones_suc=habs,
        matafuegos_suc=matafuegos,
        permisos_suc=permisos,
        estado_syh=estado_syh,
        hoy=datetime.date.today().isoformat(),
    )


@app.route("/suc/syh")
@suc_login_required
def suc_syh():
    suc_num = session["suc_nombre"].replace("Sucursal ", "").strip()
    syh_data = load_syh()
    estado = syh_data.get(suc_num, {})
    habs = [_enrich_habilitacion(h) for h in load_habilitaciones().get("habilitaciones", []) if h.get("sucursal") == session["suc_nombre"] or h.get("sucursal_num") == suc_num]
    habs.sort(key=lambda h: (ESTADO_HAB_ORDEN.get(h.get("estado"), 99), h.get("fecha_vencimiento", "9999-99-99") or "9999-99-99"))
    matafuegos = [_enrich_matafuego(m) for m in load_matafuegos().get("matafuegos", []) if m.get("sucursal") == session["suc_nombre"] or m.get("sucursal_num") == suc_num]
    matafuegos.sort(key=lambda m: (m.get("estado_calc") not in ("rechazado", "vencido"), m.get("fecha_control_calc", "9999-99-99") or "9999-99-99"))
    permisos = [p for p in _expand_permisos_para_sucursales(load_permisos().get("permisos", [])) if p.get("sucursal") == session["suc_nombre"] or p.get("sucursal_num") == suc_num]
    permisos.sort(key=lambda p: p.get("created_at", ""), reverse=True)
    return render_template(
        "suc_syh.html",
        estado=estado,
        habilitaciones_suc=habs,
        matafuegos_suc=matafuegos,
        permisos_suc=permisos,
        syh_documentos_categorias=SYH_DOCUMENTOS_CATEGORIAS,
    )


@app.route("/suc/matafuegos")
@suc_login_required
def suc_matafuegos():
    suc_num = session["suc_nombre"].replace("Sucursal ", "").strip()
    matafuegos = [_enrich_matafuego(m) for m in load_matafuegos().get("matafuegos", []) if m.get("sucursal") == session["suc_nombre"] or m.get("sucursal_num") == suc_num]
    matafuegos.sort(key=lambda m: (m.get("estado_calc") not in ("rechazado", "vencido"), m.get("fecha_control_calc", "9999-99-99") or "9999-99-99"))
    resumen = _resumen_matafuegos_sucursal(matafuegos)
    return render_template("suc_matafuegos.html", matafuegos_suc=matafuegos, resumen_matafuegos=resumen, hoy=datetime.date.today().isoformat())


@app.route("/suc/permisos/<permiso_id>/fao", methods=["POST"])
@suc_login_required
def suc_permiso_fao(permiso_id):
    suc_num = session.get("suc_nombre", "").replace("Sucursal ", "").strip()
    data = load_permisos()
    updated = False
    for p in data.get("permisos", []):
        if p.get("id") != permiso_id:
            continue
        if p.get("sucursales"):
            for d in p.get("sucursales", []):
                if d.get("sucursal_num") == suc_num:
                    d["fao_estado"] = "Contamos FAO"
                    d["fao_fecha"] = datetime.datetime.now().isoformat()
                    updated = True
        elif p.get("sucursal_num") == suc_num:
            p["fao_estado"] = "Contamos FAO"
            p["fao_fecha"] = datetime.datetime.now().isoformat()
            updated = True
    if updated:
        save_permisos(data)
    return redirect(url_for("suc_panel"))


@app.route("/suc/matafuegos/<mid>/mantenimiento", methods=["POST"])
@suc_login_required
def suc_matafuego_mantenimiento(mid):
    data = load_matafuegos()
    items = data.get("matafuegos", [])
    suc_num = session.get("suc_nombre", "").replace("Sucursal ", "").strip()
    matafuego = next((m for m in items if m.get("id") == mid and (m.get("sucursal") == session.get("suc_nombre") or m.get("sucursal_num") == suc_num)), None)
    if not matafuego:
        flash("Matafuego no encontrado")
        return redirect(url_for("suc_panel"))

    accion = request.form.get("accion_matafuego", "mantenimiento")
    observacion = request.form.get("observacion_matafuego", "").strip()
    fecha_carga = request.form.get("fecha_carga", "").strip() or datetime.date.today().isoformat()
    ahora = datetime.datetime.now().isoformat()

    matafuego["fecha_carga"] = fecha_carga
    matafuego["actualizado_por_sucursal"] = session.get("suc_user", "")
    matafuego["actualizado_at"] = ahora
    matafuego["observacion_mantenimiento"] = observacion

    if accion == "rechazado":
        matafuego["estado_manual"] = "rechazado"
        agregar_notif_admin(
            "🚨 Matafuego rechazado",
            f"Sucursal {suc_num} informó un matafuego rechazado ({matafuego.get('tipo') or 'Sin tipo'} · {matafuego.get('ubicacion') or 'Sin ubicación'}).",
            tipo="syh_matafuegos"
        )
        tickets = load_tickets()
        nuevo_ticket_id = max([t.get("id", 0) for t in tickets] + [0]) + 1
        tickets.append({
            "id": nuevo_ticket_id,
            "sucursal": session["suc_nombre"],
            "categoria": "Seguridad e Higiene",
            "subcategoria": "Matafuego rechazado",
            "descripcion": observacion or f"Matafuego rechazado en {matafuego.get('ubicacion') or 'sin ubicación'}",
            "prioridad": 2,
            "estado": "Nuevo",
            "asignado": "Patricia",
            "creado": ahora,
            "actualizado": ahora,
            "historial": [{"autor": session.get("suc_nombre", "Sucursal"), "texto": f"Matafuego rechazado: {matafuego.get('tipo') or 'Sin tipo'} · {matafuego.get('ubicacion') or 'Sin ubicación'}", "fecha": ahora}],
            "tipo": "syh_matafuego_rechazado",
        })
        save_tickets(tickets)
        flash("Se registró el rechazo y se notificó a Seguridad e Higiene")
    else:
        matafuego["estado_manual"] = ""
        flash("Mantenimiento anual registrado")

    save_matafuegos(data)
    sync_alertas_syh()
    return redirect(url_for("suc_panel"))


@app.route("/mis-proveedores")
@suc_login_required
def suc_proveedores():
    suc_num = session["suc_nombre"].replace("Sucursal ", "").strip()
    mis_proveedores = []
    for p in PROVEEDORES:
        for s in p["sucursales"]:
            if s == suc_num or s == suc_num.lstrip("0"):
                if p.get("tipo") == "Fumigaciones" and p.get("mostrar_sucursal") is False:
                    continue
                mis_proveedores.append(p)
                break
    return render_template("suc_proveedores.html", mis_proveedores=mis_proveedores)


@app.route("/nuevo", methods=["GET", "POST"])
@suc_login_required
def nuevo_ticket():
    if request.method == "POST":
        tickets = load_tickets()
        tid = next_ticket_id(tickets)

        # Handle photo uploads
        fotos = []
        for f in request.files.getlist("fotos"):
            if f and f.filename:
                ext = Path(f.filename).suffix.lower()
                if ext in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
                    fname = f"{tid}_{uuid.uuid4().hex[:8]}{ext}"
                    f.save(str(UPLOADS_DIR / fname))
                    fotos.append(fname)

        subcategoria = request.form.get("subcategoria", "")
        categoria = request.form.get("categoria", "")
        solicitante_nombre = request.form.get("solicitante_nombre", "").strip()
        solicitante_apellido = request.form.get("solicitante_apellido", "").strip()
        zona_afectada = request.form.get("zona_afectada", "").strip()

        presupuestos_suc = []
        for n in range(1, 4):
            prov = request.form.get(f"ppto_proveedor_{n}", "").strip()
            monto = request.form.get(f"ppto_monto_{n}", "").strip()
            f_pres = request.files.get(f"ppto_archivo_{n}")
            archivo = ""
            archivo_nombre = ""
            if f_pres and f_pres.filename:
                ext = Path(f_pres.filename).suffix.lower()
                if ext in (".pdf", ".jpg", ".jpeg", ".png"):
                    archivo = f"{tid}_ppto_suc_{n}_{uuid.uuid4().hex[:8]}{ext}"
                    f_pres.save(str(UPLOADS_DIR / archivo))
                    archivo_nombre = f_pres.filename
            if prov or archivo:
                presupuestos_suc.append({
                    "autor": session.get("suc_nombre", "Sucursal"),
                    "fecha": datetime.datetime.now().isoformat(),
                    "detalle": request.form.get("descripcion", "").strip(),
                    "proveedor": prov,
                    "monto": monto,
                    "archivo": archivo,
                    "archivo_nombre": archivo_nombre,
                })
        proveedor_presupuesto = presupuestos_suc[0]["proveedor"] if presupuestos_suc else ""
        ticket = {
            "id": tid,
            "sucursal": session.get("suc_nombre", request.form.get("sucursal", "")),
            "categoria": categoria,
            "subcategoria": subcategoria,
            "descripcion": request.form.get("descripcion", ""),
            "solicitante_nombre": solicitante_nombre,
            "solicitante_apellido": solicitante_apellido,
            "solicitante": f"{solicitante_nombre} {solicitante_apellido}".strip(),
            "prioridad": auto_priority(categoria, subcategoria),
            "estado": "Nuevo",
            "asignado": auto_assign(subcategoria, session.get("suc_nombre", request.form.get("sucursal", "")), categoria),
            "fotos": fotos,
            "observaciones": "",
            "creado": datetime.datetime.now().isoformat(),
            "actualizado": datetime.datetime.now().isoformat(),
        }

        if categoria == "Materiales":
            ticket["categoria_mat"] = request.form.get("categoria_mat", "").strip()
            ticket["subitem_mat"] = request.form.get("subitem_mat", "").strip()
            ticket["cantidad_mat"] = request.form.get("cantidad_mat", "1").strip()
        elif categoria == "Presupuestos":
            if not proveedor_presupuesto:
                flash("En presupuestos, el proveedor es obligatorio")
                return redirect(url_for("nuevo_ticket"))
            if not zona_afectada:
                flash("En presupuestos, la zona afectada es obligatoria")
                return redirect(url_for("nuevo_ticket"))
            ticket["estado_presupuesto"] = "Nuevo"
            ticket["zona_afectada"] = zona_afectada
            ticket["respuesta_sucursal_presupuesto"] = ""
            ticket["proveedor_presupuesto"] = proveedor_presupuesto
            if presupuestos_suc:
                ticket["presupuestos"] = presupuestos_suc
        elif categoria == "Seguridad e Higiene":
            ticket["tipo"] = "syh_general"

        tickets.append(ticket)
        save_tickets(tickets)
        return render_template("ticket_creado.html", ticket=ticket)

    from categories_data import MATERIAL_CATEGORIAS
    sucursal = request.args.get("sucursal", "")
    return render_template(
        "nuevo_ticket.html",
        sucursales=SUCURSALES,
        categorias=CATEGORIAS,
        prioridades=PRIORIDADES,
        sucursal_selected=sucursal,
        material_categorias=MATERIAL_CATEGORIAS,
    )


@app.route("/estado/<int:ticket_id>")
def estado_ticket(ticket_id):
    tickets = load_tickets()
    ticket = next((t for t in tickets if t["id"] == ticket_id), None)
    if not ticket:
        return "Ticket no encontrado", 404
    suc_num = str(ticket.get("sucursal_num", "") or ticket.get("sucursal", "")).replace("Sucursal ", "").strip()
    tiene_abono = bool(get_proveedor_abono_sucursal(suc_num))
    return render_template("estado_ticket.html", ticket=ticket, prioridades=PRIORIDADES, tiene_abono=tiene_abono)


@app.route("/confirmar-recepcion/<int:ticket_id>", methods=["POST"])
@suc_login_required
def confirmar_recepcion(ticket_id):
    tickets = load_tickets()
    ticket = next((t for t in tickets if t["id"] == ticket_id), None)
    if not ticket:
        return "Ticket no encontrado", 404

    if ticket.get("sucursal") != session.get("suc_nombre"):
        return render_template("error.html", mensaje="No tenés permiso para confirmar este ticket."), 403

    if "notas" not in ticket:
        ticket["notas"] = []

    # Handle remito upload
    remito_file = ""
    f = request.files.get("remito")
    if f and f.filename:
        ext = Path(f.filename).suffix.lower()
        fname = f"{ticket_id}_remito_{uuid.uuid4().hex[:8]}{ext}"
        f.save(str(UPLOADS_DIR / fname))
        remito_file = fname

    comentario = request.form.get("comentario", "").strip()
    nota_texto = "Materiales recibidos en sucursal"
    if comentario:
        nota_texto += f": {comentario}"

    nota = {
        "autor": session.get("suc_nombre", "Sucursal"),
        "fecha": datetime.datetime.now().isoformat(),
        "texto": nota_texto,
    }
    if remito_file:
        nota["fotos"] = [remito_file]

    ticket["notas"].append(nota)
    ticket["materiales_recibidos"] = True
    ticket["estado"] = "Materiales recibidos"
    ticket["actualizado"] = datetime.datetime.now().isoformat()

    agregar_notif_admin(
        titulo=f"Materiales recibidos #{ticket_id} — definir siguiente paso",
        detalle=f"{ticket['sucursal']} confirmó recepción de materiales. Decidir cómo se realizará el trabajo.",
        tipo="equipo_central",
        autor=session.get("suc_nombre", "Sucursal"),
        link=url_for("admin_ticket", ticket_id=ticket_id),
    )

    save_tickets(tickets)
    flash("Recepcion confirmada")
    return redirect(url_for("estado_ticket", ticket_id=ticket_id))


# --- Routes: Admin panel ---

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        user = request.form.get("usuario", "").lower()
        pwd = request.form.get("password", "")
        if user in ADMINS and ADMINS[user]["password"] == pwd:
            session["user"] = user
            session["nombre"] = ADMINS[user]["nombre"]
            session["rol"] = ADMINS[user]["rol"]
            return redirect(url_for("admin_panel"))
        flash("Usuario o contraseña incorrectos")
    return render_template("admin_login.html")


@app.route("/admin/logout", methods=["GET", "POST"])
def admin_logout():
    session.clear()
    return redirect(url_for("admin_login"))


@app.route("/admin")
@login_required
def admin_panel():
    # Jonathan (tecnico) va directo a sus pedidos
    if session.get("rol") == "tecnico":
        return redirect(url_for("admin_pedidos"))
    sync_alertas_syh()
    tickets = load_tickets()
    filtro_estado = request.args.get("estado", "")
    filtro_suc = request.args.get("sucursal", "")
    filtro_prioridad = request.args.get("prioridad", "")

    es_rita = session.get("nombre") == "Rita"
    if es_rita:
        filtered = [t for t in tickets if t.get("categoria") == "Presupuestos" and t.get("requiere_requisicion") and t.get("estado_presupuesto") == "Aprobado"]
    else:
        filtered = tickets
        if filtro_estado:
            filtered = [t for t in filtered if t["estado"] == filtro_estado]
        if filtro_suc:
            filtered = [t for t in filtered if t["sucursal"] == filtro_suc]
        if filtro_prioridad:
            filtered = [t for t in filtered if t["prioridad"] == int(filtro_prioridad)]

    stats = {
        "total": len(tickets),
        "nuevos": sum(1 for t in tickets if t["estado"] in ("Nuevo", "Abierto")),
        "en_progreso": sum(1 for t in tickets if t["estado"] in ("En progreso", "Pendiente")),
        "resueltos": sum(1 for t in tickets if t["estado"] == "Resuelto"),
    }

    # Chart data
    from collections import Counter
    prioridad_counts = Counter(PRIORIDADES.get(t["prioridad"], "?") for t in tickets)
    categoria_counts = Counter(t.get("categoria", "Otro") for t in tickets)
    asignado_counts = Counter(t.get("asignado", "Sin asignar") for t in tickets)

    # My work counts
    user_nombre = session.get("nombre", "")
    def _es_ticket_para_seguimiento_admin(t):
        if t.get("categoria") == "Presupuestos":
            return True
        suc = (t.get("sucursal") or "")
        suc_num = suc.replace("Sucursal ", "").strip()
        asignado = t.get("asignado") or ""
        return (
            suc_num
            and not get_proveedor_abono_sucursal(suc_num)
            and asignado in (user_nombre, ASIGNACION_DEFAULT, "", None)
        )

    mis_esperando = [t for t in tickets if (t.get("asignado") == user_nombre or _es_ticket_para_seguimiento_admin(t)) and t["estado"] in ("Nuevo", "Abierto")]
    mis_asignados = [t for t in tickets if (t.get("asignado") == user_nombre or _es_ticket_para_seguimiento_admin(t)) and t["estado"] not in ("Resuelto", "Cerrado")]
    sin_asignar = [t for t in tickets if not t.get("asignado") or t.get("asignado") == ""]
    tickets_rita_pendientes = [t for t in tickets if t.get("categoria") == "Presupuestos" and t.get("requiere_requisicion") and t.get("estado_presupuesto") == "Aprobado"]

    vista = request.args.get("vista", "dashboard")
    if vista == "tarjetas":
        if es_rita:
            filtered = list(tickets_rita_pendientes)
        else:
            filtered = list(mis_asignados)
            if filtro_estado:
                filtered = [t for t in filtered if t["estado"] == filtro_estado]
            if filtro_suc:
                filtered = [t for t in filtered if t["sucursal"] == filtro_suc]
            if filtro_prioridad:
                filtered = [t for t in filtered if t["prioridad"] == int(filtro_prioridad)]

    filtered.sort(key=lambda t: t["creado"], reverse=True)

    # Alertas: tickets > 150 dias (5 meses)
    alertas = []
    for t in tickets:
        if t["estado"] not in ("Resuelto", "Cerrado"):
            try:
                created = datetime.datetime.fromisoformat(t["creado"])
                age = (datetime.datetime.now() - created).days
                if age > 150:
                    t["dias"] = age
                    alertas.append(t)
            except (ValueError, KeyError):
                pass
    alertas.sort(key=lambda t: t.get("dias", 0), reverse=True)

    # Notificaciones admin (stock / facturas cargadas)
    notif_data = load_notif_admin()
    notif_admin = [n for n in notif_data.get("notificaciones", []) if not n.get("leida")]
    notif_tipo_labels = {
        "stock": "Stock",
        "factura": "Contabilidad",
        "equipo_central": "Equipo Central",
        "syh_matafuegos": "Matafuegos",
        "syh_habilitacion": "Habilitaciones",
        "syh": "Seguridad e Higiene",
    }
    notif_admin = [
        {
            **n,
            "tipo_label": notif_tipo_labels.get(n.get("tipo"), (n.get("tipo") or "General").replace("_", " ").title()),
            "es_critica": n.get("tipo") in ("syh_matafuegos", "syh_habilitacion") or "🚨" in (n.get("titulo") or ""),
        }
        for n in notif_admin[:12]
    ]

    return render_template(
        "admin_panel.html",
        tickets=filtered,
        stats=stats,
        estados=ESTADOS,
        sucursales=SUCURSALES,
        prioridades=PRIORIDADES,
        filtro_estado=filtro_estado,
        filtro_suc=filtro_suc,
        filtro_prioridad=filtro_prioridad,
        prioridad_counts=dict(prioridad_counts),
        categoria_counts=dict(categoria_counts),
        asignado_counts=dict(asignado_counts),
        mis_esperando=len(mis_esperando),
        mis_asignados=len(mis_asignados),
        sin_asignar_count=len(sin_asignar),
        notif_criticas=sum(1 for n in notif_admin if n.get("es_critica")),
        vista=vista,
        alertas=alertas,
        notif_admin=notif_admin,
        tickets_rita_pendientes=tickets_rita_pendientes,
        es_rita=es_rita,
    )


@app.route("/admin/ceyh")
@admin_required
def admin_ceyh():
    tickets = load_tickets()
    retiros_data = load_ceyh_retiros()
    jornadas_data = load_ceyh_jornadas()
    ceyh = [_normalize_ceyh_ticket(t) for t in tickets if es_ticket_ceyh(t)]
    activos = [t for t in ceyh if t.get("estado") not in ("Resuelto", "Cerrado")]
    derivados = [t for t in ceyh if t.get("derivado_desde") == "CEYH" and t.get("asignado") == "Equipo Central"]
    terminados = [t for t in ceyh if t.get("estado") in ("Resuelto", "Cerrado")]
    retiros = list(retiros_data.get("retiros", []))
    retiros.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    jornadas = list(jornadas_data.get("jornadas", []))
    jornadas.sort(key=lambda j: j.get("fecha", ""), reverse=True)
    jornada_hoy = next((j for j in jornadas if j.get("fecha") == datetime.date.today().isoformat()), None)

    esperando_materiales = [t for t in activos if t.get("estado_materiales") == "Pendiente"]
    listos_retiro = [t for t in activos if t.get("estado_retiro") == "Listo para retirar"]
    en_ruta = [t for t in activos if t.get("estado_operativo_ceyh") == "En ruta"]
    demorados = [t for t in activos if t.get("estado_operativo_ceyh") == "Demorado"]

    activos.sort(key=lambda t: (int(t.get("prioridad") or 4), t.get("fecha_objetivo") or "9999-99-99", t.get("creado") or ""))
    derivados.sort(key=lambda t: t.get("actualizado") or "", reverse=True)
    terminados.sort(key=lambda t: t.get("actualizado") or "", reverse=True)

    return render_template(
        "admin_ceyh.html",
        activos=activos,
        derivados=derivados,
        terminados=terminados,
        retiros=retiros,
        jornadas=jornadas,
        jornada_hoy=jornada_hoy,
        esperando_materiales=esperando_materiales,
        listos_retiro=listos_retiro,
        en_ruta=en_ruta,
        demorados=demorados,
        prioridades=PRIORIDADES,
    )


@app.route("/admin/ceyh/jornada/<jid>/modificar", methods=["POST"])
@admin_required
def admin_ceyh_jornada_modificar(jid):
    data = load_ceyh_jornadas()
    jornada = next((j for j in data.get("jornadas", []) if j.get("id") == jid), None)
    if not jornada:
        flash("Jornada no encontrada")
        return redirect(url_for("admin_ceyh"))

    jornada["camioneta"] = request.form.get("camioneta", jornada.get("camioneta", "")).strip()
    jornada["cuadrilla"] = request.form.get("cuadrilla", jornada.get("cuadrilla", "")).strip()
    jornada["observaciones"] = request.form.get("observaciones", jornada.get("observaciones", "")).strip()
    jornada["cambio_ruta"] = request.form.get("cambio_ruta", "").strip()
    jornada["updated_at"] = datetime.datetime.now().isoformat()
    save_ceyh_jornadas(data)
    flash("Ruta / jornada actualizada")
    return redirect(url_for("admin_ceyh"))


@app.route("/admin/ceyh/retiro", methods=["POST"])
@admin_required
def admin_ceyh_retiro():
    tickets = load_tickets()
    ticket_id = request.form.get("ticket_id", "").strip()
    ticket = next((t for t in tickets if str(t.get("id")) == ticket_id), None)
    if not ticket:
        flash("Ticket no encontrado")
        return redirect(url_for("admin_ceyh"))

    data = load_ceyh_retiros()
    retiro = {
        "id": uuid.uuid4().hex[:12],
        "ticket_id": ticket.get("id"),
        "sucursal": ticket.get("sucursal", ""),
        "materiales": request.form.get("materiales", "").strip(),
        "estado": request.form.get("estado", "Pendiente de preparación").strip(),
        "preparado_por": request.form.get("preparado_por", "").strip(),
        "retirado_por": request.form.get("retirado_por", "").strip(),
        "fecha_preparado": request.form.get("fecha_preparado", "").strip(),
        "fecha_retiro": request.form.get("fecha_retiro", "").strip(),
        "fecha_entrega": request.form.get("fecha_entrega", "").strip(),
        "observaciones": request.form.get("observaciones", "").strip(),
        "created_at": datetime.datetime.now().isoformat(),
        "creado_por": session.get("nombre", "Admin"),
    }
    data.setdefault("retiros", []).append(retiro)
    save_ceyh_retiros(data)

    ticket = _normalize_ceyh_ticket(ticket)
    ticket["requiere_materiales"] = True
    ticket["requiere_retiro_central"] = True
    ticket["estado_materiales"] = "Pendiente" if retiro["estado"] == "Pendiente de preparación" else ticket.get("estado_materiales", "Pendiente")
    ticket["estado_retiro"] = retiro["estado"]
    ticket.setdefault("notas", []).append({
        "autor": session.get("nombre", "Admin"),
        "fecha": datetime.datetime.now().isoformat(),
        "texto": f"Retiro CEYH creado: {retiro['estado']} - {retiro['materiales'][:120]}",
    })
    ticket["actualizado"] = datetime.datetime.now().isoformat()
    save_tickets(tickets)
    flash("Retiro CEYH registrado")
    return redirect(url_for("admin_ceyh"))


@app.route("/admin/ceyh/jornada", methods=["POST"])
@admin_required
def admin_ceyh_jornada():
    tickets = load_tickets()
    data = load_ceyh_jornadas()
    fecha = request.form.get("fecha", datetime.date.today().isoformat()).strip() or datetime.date.today().isoformat()
    camioneta = request.form.get("camioneta", "").strip()
    cuadrilla = request.form.get("cuadrilla", "").strip()
    ticket_ids = request.form.getlist("ticket_ids")
    urgencias_ids = request.form.getlist("urgencia_ids")

    planificados = []
    for idx, tid in enumerate(ticket_ids, start=1):
        t = next((x for x in tickets if str(x.get("id")) == str(tid)), None)
        if not t:
            continue
        planificados.append({
            "ticket_id": t.get("id"),
            "sucursal": t.get("sucursal", ""),
            "prioridad": t.get("prioridad", 4),
            "tipo": t.get("subcategoria") or t.get("categoria", ""),
            "orden": idx,
            "estado_jornada": "planificado",
        })
        _normalize_ceyh_ticket(t)
        t["estado_operativo_ceyh"] = "Planificado"
        t["actualizado"] = datetime.datetime.now().isoformat()

    urgencias = []
    for idx, tid in enumerate(urgencias_ids, start=1):
        t = next((x for x in tickets if str(x.get("id")) == str(tid)), None)
        if not t:
            continue
        urgencias.append({
            "ticket_id": t.get("id"),
            "sucursal": t.get("sucursal", ""),
            "prioridad": t.get("prioridad", 4),
            "tipo": t.get("subcategoria") or t.get("categoria", ""),
            "orden": idx,
            "estado_jornada": "urgencia_agregada",
        })
        _normalize_ceyh_ticket(t)
        t["estado_operativo_ceyh"] = "Planificado"
        t.setdefault("notas", []).append({
            "autor": session.get("nombre", "Admin"),
            "fecha": datetime.datetime.now().isoformat(),
            "texto": "Agregado a jornada CEYH como urgencia",
        })
        t["actualizado"] = datetime.datetime.now().isoformat()

    jornada = {
        "id": uuid.uuid4().hex[:12],
        "fecha": fecha,
        "camioneta": camioneta,
        "cuadrilla": cuadrilla,
        "planificados": planificados,
        "urgencias": urgencias,
        "observaciones": request.form.get("observaciones", "").strip(),
        "estado": "abierta",
        "created_at": datetime.datetime.now().isoformat(),
        "creado_por": session.get("nombre", "Admin"),
    }
    data.setdefault("jornadas", []).append(jornada)
    save_ceyh_jornadas(data)
    save_tickets(tickets)
    flash("Jornada CEYH creada")
    return redirect(url_for("admin_ceyh"))


@app.route("/admin/permisos", methods=["GET", "POST"])
@admin_required
def admin_permisos():
    data = load_permisos()

    if request.method == "POST":
        sucursal = request.form.get("sucursal", "").strip()
        sucursales_multi = request.form.getlist("sucursales")
        proveedor = request.form.get("proveedor", "").strip()
        destinos_raw = sucursales_multi or ([sucursal] if sucursal else [])
        if not destinos_raw:
            flash("Seleccione al menos una sucursal")
            return redirect(url_for("admin_permisos"))

        archivo = ""
        f = request.files.get("archivo")
        if f and f.filename:
            ext = Path(f.filename).suffix.lower()
            if ext not in (".pdf", ".jpg", ".jpeg", ".png"):
                flash("Formato no permitido (solo PDF, JPG, PNG)")
                return redirect(url_for("admin_permisos"))
            fname = f"perm_{uuid.uuid4().hex[:10]}{ext}"
            f.save(str(PERMISOS_DIR / fname))
            archivo = fname
        else:
            flash("Adjuntá un archivo")
            return redirect(url_for("admin_permisos"))

        destinos = []
        for suc in destinos_raw:
            suc = (suc or "").strip()
            if not suc:
                continue
            destinos.append({
                "id": uuid.uuid4().hex[:8],
                "sucursal": suc,
                "sucursal_num": suc.replace("Sucursal ", "").strip(),
                "fao_estado": "Pendiente",
                "fao_fecha": "",
            })

        data.setdefault("permisos", []).append({
            "id": uuid.uuid4().hex[:12],
            "sucursal": destinos[0]["sucursal"] if len(destinos) == 1 else "",
            "sucursal_num": destinos[0]["sucursal_num"] if len(destinos) == 1 else "",
            "sucursales": destinos,
            "proveedor": proveedor,
            "tipo_documento": request.form.get("tipo_documento", "Nómina / Permiso de ingreso").strip(),
            "periodo": request.form.get("periodo", "").strip(),
            "vigencia_desde": request.form.get("vigencia_desde", "").strip(),
            "vigencia_hasta": request.form.get("vigencia_hasta", "").strip(),
            "comentario": request.form.get("comentario", "").strip(),
            "archivo": archivo,
            "archivo_nombre": f.filename,
            "cargado_por": session.get("nombre", ""),
            "created_at": datetime.datetime.now().isoformat(),
        })
        save_permisos(data)
        flash("Permiso cargado")
        return redirect(url_for("admin_permisos"))

    permisos = _expand_permisos_para_sucursales(list(data.get("permisos", [])))
    filtro_suc = request.args.get("sucursal", "").strip()
    if filtro_suc:
        permisos = [p for p in permisos if p.get("sucursal") == filtro_suc]
    permisos.sort(key=lambda p: p.get("created_at", ""), reverse=True)
    return render_template("admin_permisos.html", permisos=permisos, sucursales=SUCURSALES, filtro_suc=filtro_suc)


@app.route("/uploads/permisos/<filename>")
@any_session_required
def serve_permiso(filename):
    return send_from_directory(str(PERMISOS_DIR), filename)


@app.route("/admin/presupuestos", methods=["GET", "POST"])
@login_required
def admin_presupuestos():
    tickets = load_tickets()
    presupuesto_tickets = [t for t in tickets if t.get("categoria") == "Presupuestos"]
    filtro_suc = request.args.get("sucursal", "").strip()
    filtro_estado = request.args.get("estado", "").strip()

    if filtro_suc:
        presupuesto_tickets = [t for t in presupuesto_tickets if t.get("sucursal") == filtro_suc]
    if filtro_estado:
        presupuesto_tickets = [t for t in presupuesto_tickets if (t.get("estado_presupuesto") or "Nuevo") == filtro_estado]

    presupuesto_tickets.sort(key=lambda x: x.get("actualizado", ""), reverse=True)
    return render_template("admin_presupuestos.html", presupuestos=presupuesto_tickets, sucursales=SUCURSALES, tickets=tickets, filtro_suc=filtro_suc, filtro_estado=filtro_estado)


@app.route("/uploads/presupuestos/<filename>")
@any_session_required
def serve_presupuesto(filename):
    return send_from_directory(str(PRESUPUESTOS_DIR), filename)


@app.route("/uploads/requisiciones/<filename>")
@login_required
def serve_requisicion(filename):
    return send_from_directory(str(REQUISICIONES_DIR), filename)


@app.route("/admin/ticket/<int:ticket_id>", methods=["GET", "POST"])
@login_required
def admin_ticket(ticket_id):
    tickets = load_tickets()
    ticket = next((t for t in tickets if t["id"] == ticket_id), None)
    if not ticket:
        return "Ticket no encontrado", 404
    ticket = _normalize_ceyh_ticket(ticket)

    if request.method == "POST":
        accion = request.form.get("accion", "")
        # Accion rapida: responder a la sucursal con una de las 3 opciones
        if accion == "responder_suc":
            motivo = request.form.get("motivo", "").strip()
            detalle = request.form.get("motivo_detalle", "").strip()
            labels = {
                "esperando_proveedor": "Esperando proveedor",
                "esperando_materiales": "Esperando materiales",
                "otra": "Otra",
            }
            label = labels.get(motivo, motivo)
            mensaje = label if motivo != "otra" else (detalle or label)
            if detalle and motivo != "otra":
                mensaje += f" - {detalle}"
            if "notas" not in ticket:
                ticket["notas"] = []
            ticket["notas"].append({
                "autor": session.get("nombre", "Admin"),
                "fecha": datetime.datetime.now().isoformat(),
                "texto": f"Respuesta a sucursal: {mensaje}",
            })
            if "notificaciones" not in ticket:
                ticket["notificaciones"] = []
            ticket["notificaciones"].append({
                "fecha": datetime.datetime.now().isoformat(),
                "texto": mensaje,
                "leida": False,
            })
            ticket["estado_respuesta"] = label
            if ticket.get("categoria") == "Presupuestos":
                ticket["respuesta_sucursal_presupuesto"] = mensaje
            if ticket["estado"] in ("Nuevo", "Abierto"):
                ticket["estado"] = "Pendiente"
            ticket["actualizado"] = datetime.datetime.now().isoformat()
            save_tickets(tickets)
            flash("Respuesta enviada a la sucursal")
            return redirect(url_for("admin_ticket", ticket_id=ticket_id))

        if accion == "estado_presupuesto":
            nuevo_estado = request.form.get("nuevo_estado_presupuesto", "").strip() or "Nuevo"
            comentario = request.form.get("comentario_presupuesto", "").strip()
            ticket["estado_presupuesto"] = nuevo_estado
            ticket["estado"] = "Pendiente" if nuevo_estado == "Nuevo" else nuevo_estado
            if nuevo_estado == "Aprobado":
                ticket["requiere_requisicion"] = True
                ticket["asignado_rita"] = True
                ticket.setdefault("notificaciones", []).append({
                    "fecha": datetime.datetime.now().isoformat(),
                    "texto": "Presupuesto aprobado. El proveedor puede avanzar.",
                    "leida": False,
                })
            elif nuevo_estado == "Rechazado":
                ticket["requiere_requisicion"] = False
            if comentario:
                ticket.setdefault("notas", []).append({
                    "autor": session.get("nombre", "Admin"),
                    "fecha": datetime.datetime.now().isoformat(),
                    "texto": f"Presupuesto {nuevo_estado}: {comentario}",
                })
                ticket.setdefault("notificaciones", []).append({
                    "fecha": datetime.datetime.now().isoformat(),
                    "texto": comentario,
                    "leida": False,
                })
                ticket["respuesta_sucursal_presupuesto"] = comentario
            else:
                ticket.setdefault("notas", []).append({
                    "autor": session.get("nombre", "Admin"),
                    "fecha": datetime.datetime.now().isoformat(),
                    "texto": f"Estado de presupuesto actualizado a {nuevo_estado}",
                })
            ticket["actualizado"] = datetime.datetime.now().isoformat()
            save_tickets(tickets)
            flash("Estado del presupuesto actualizado")
            return redirect(url_for("admin_ticket", ticket_id=ticket_id))

        if accion == "cargar_requisicion":
            req_numero = request.form.get("requisicion_numero", "").strip()
            req_nota = request.form.get("requisicion_nota", "").strip()
            if not req_numero:
                flash("Ingresá el número de requisición")
                return redirect(url_for("admin_ticket", ticket_id=ticket_id))
            archivo = request.files.get("archivo_requisicion")
            archivo_guardado = None
            archivo_nombre = None
            if archivo and archivo.filename:
                ext = os.path.splitext(archivo.filename)[1].lower()
                archivo_guardado = f"req_{ticket_id}_{uuid.uuid4().hex[:8]}{ext}"
                archivo.save(str(REQUISICIONES_DIR / archivo_guardado))
                archivo_nombre = archivo.filename
            ticket["requisicion_numero"] = req_numero
            ticket["requisicion_fecha"] = datetime.datetime.now().isoformat()
            ticket["requisicion_por"] = session.get("nombre", "Rita")
            if archivo_guardado:
                ticket["requisicion_archivo"] = archivo_guardado
                ticket["requisicion_archivo_nombre"] = archivo_nombre
            ticket["requiere_requisicion"] = False
            nota_texto = f"Requisición cargada: #{req_numero}"
            if req_nota:
                nota_texto += f" — {req_nota}"
            ticket.setdefault("notas", []).append({
                "autor": session.get("nombre", "Rita"),
                "fecha": datetime.datetime.now().isoformat(),
                "texto": nota_texto,
            })
            ticket["actualizado"] = datetime.datetime.now().isoformat()
            save_tickets(tickets)
            archivo_path = str(REQUISICIONES_DIR / archivo_guardado) if archivo_guardado else None
            email_ok = _enviar_requisicion_compras(ticket, req_numero, archivo_path, archivo_nombre)
            flash("Requisición cargada y mail enviado a Compras" if email_ok else "Requisición cargada (no se pudo enviar el mail)")
            return redirect(url_for("admin_ticket", ticket_id=ticket_id))

        if accion == "derivar_equipo_desde_ceyh":
            ticket["derivado_desde"] = "CEYH"
            ticket["asignado"] = "Equipo Central"
            ticket["siguiente_paso"] = "personal_mantenimiento"
            ticket["asignado_equipo"] = "Equipo Central"
            ticket["etapa_equipo"] = "asignado"
            ticket["estado"] = "Abierto" if ticket.get("estado") == "Nuevo" else ticket.get("estado", "Abierto")
            ticket.setdefault("notas", []).append({
                "autor": session.get("nombre", "Admin"),
                "fecha": datetime.datetime.now().isoformat(),
                "texto": "Derivado por admin desde CEYH a Equipo Central",
            })
            ticket["actualizado"] = datetime.datetime.now().isoformat()
            save_tickets(tickets)
            flash("Ticket derivado a Equipo Central")
            return redirect(url_for("admin_ticket", ticket_id=ticket_id))

        if accion == "actualizar_ceyh":
            ticket["requiere_materiales"] = bool(request.form.get("requiere_materiales"))
            ticket["estado_materiales"] = request.form.get("estado_materiales", ticket.get("estado_materiales", "No requiere"))
            ticket["requiere_retiro_central"] = bool(request.form.get("requiere_retiro_central"))
            ticket["estado_retiro"] = request.form.get("estado_retiro", ticket.get("estado_retiro", "No requiere"))
            ticket["cuadrilla_ceyh"] = request.form.get("cuadrilla_ceyh", "").strip()
            ticket["camioneta_ceyh"] = request.form.get("camioneta_ceyh", "").strip()
            ticket["ultima_novedad_operativa"] = request.form.get("ultima_novedad_operativa", "").strip()
            ticket["proxima_accion"] = request.form.get("proxima_accion", "").strip()
            ticket["fecha_objetivo"] = request.form.get("fecha_objetivo", "").strip()
            ticket["estado_operativo_ceyh"] = request.form.get("estado_operativo_ceyh", ticket.get("estado_operativo_ceyh", "Pendiente"))
            ticket.setdefault("notas", []).append({
                "autor": session.get("nombre", "Admin"),
                "fecha": datetime.datetime.now().isoformat(),
                "texto": f"Actualización CEYH: estado operativo {ticket['estado_operativo_ceyh']}, materiales {ticket['estado_materiales']}, retiro {ticket['estado_retiro']}",
            })
            ticket["actualizado"] = datetime.datetime.now().isoformat()
            save_tickets(tickets)
            flash("Control operativo CEYH actualizado")
            return redirect(url_for("admin_ticket", ticket_id=ticket_id))

        if accion == "definir_siguiente_paso":
            siguiente_paso = request.form.get("siguiente_paso", "").strip()
            _paso_labels = {
                "personal_mantenimiento": "Personal de Mantenimiento Central",
                "proveedor_abono": "Proveedor del abono mensual",
                "proveedor_eventual": "Proveedor eventual",
                "sucursal": "Personal propio de la sucursal",
            }
            if siguiente_paso not in _paso_labels:
                flash("Seleccioná una opción")
                return redirect(url_for("admin_ticket", ticket_id=ticket_id))
            ticket["siguiente_paso"] = siguiente_paso
            ticket["estado"] = "Cerrado" if siguiente_paso == "sucursal" else "En progreso"
            if siguiente_paso == "personal_mantenimiento":
                ticket["asignado_equipo"] = "Equipo Central"
                ticket.setdefault("etapa_equipo", "asignado")
            ticket.setdefault("notas", []).append({
                "autor": session.get("nombre", "Admin"),
                "fecha": datetime.datetime.now().isoformat(),
                "texto": f"Siguiente paso definido: {_paso_labels[siguiente_paso]}",
            })
            ticket.setdefault("notificaciones", []).append({
                "fecha": datetime.datetime.now().isoformat(),
                "texto": f"El equipo de administración definió el siguiente paso: {_paso_labels[siguiente_paso]}.",
                "leida": False,
            })
            if siguiente_paso == "proveedor_abono":
                suc_num = ticket["sucursal"].replace("Sucursal ", "").strip()
                prov_abono = get_proveedor_abono_sucursal(suc_num)
                if prov_abono:
                    now_iso = datetime.datetime.now().isoformat()
                    new_id = next_ticket_id(tickets)
                    descripcion_nueva = (ticket.get("descripcion", "") or "").strip()
                    descripcion_nueva += "\n\nRequiere trabajo con materiales recibidos en sucursal"
                    nuevo = {
                        "id": new_id,
                        "tipo": "trabajo_proveedor",
                        "sucursal": ticket["sucursal"],
                        "origen_ticket_id": ticket["id"],
                        "descripcion": descripcion_nueva,
                        "estado": "Nuevo",
                        "asignado_proveedor": prov_abono,
                        "asignado": prov_abono,
                        "prioridad": ticket.get("prioridad", 3),
                        "creado": now_iso,
                        "actualizado": now_iso,
                        "categoria": "Trabajo con materiales",
                        "subcategoria": ticket.get("subcategoria", ""),
                        "fotos": [],
                        "notas": [{"autor": "Sistema", "fecha": now_iso, "texto": f"Ticket generado desde pedido de materiales #{ticket['id']}"}],
                    }
                    tickets.append(nuevo)
                    ticket["trabajo_proveedor_ticket_id"] = new_id
                    ticket.setdefault("notas", []).append({
                        "autor": "Sistema",
                        "fecha": now_iso,
                        "texto": f"Se creó ticket #{new_id} asignado a {prov_abono} para ejecutar el trabajo",
                    })
            ticket["actualizado"] = datetime.datetime.now().isoformat()
            save_tickets(tickets)
            flash(f"Siguiente paso definido: {_paso_labels[siguiente_paso]}")
            return redirect(url_for("admin_ticket", ticket_id=ticket_id))

        if accion == "resolver_matafuego_rechazado":
            detalle = request.form.get("detalle_resolucion", "").strip()
            ticket["estado"] = "Resuelto"
            ticket.setdefault("notas", []).append({
                "autor": session.get("nombre", "Admin"),
                "fecha": datetime.datetime.now().isoformat(),
                "texto": f"Rechazo de matafuego resuelto{': ' + detalle if detalle else ''}",
            })
            ticket["actualizado"] = datetime.datetime.now().isoformat()
            save_tickets(tickets)
            flash("Caso de matafuego rechazado marcado como resuelto")
            return redirect(url_for("admin_ticket", ticket_id=ticket_id))

        # Check if it's a note or an update
        nueva_nota = request.form.get("nueva_nota", "").strip()
        if nueva_nota:
            if "notas" not in ticket:
                ticket["notas"] = []
            ticket["notas"].append({
                "autor": session.get("nombre", "?"),
                "fecha": datetime.datetime.now().isoformat(),
                "texto": nueva_nota,
            })
        else:
            ticket["estado"] = request.form.get("estado", ticket["estado"])
            ticket["asignado"] = request.form.get("asignado", ticket["asignado"])
            ticket["prioridad"] = int(request.form.get("prioridad", ticket["prioridad"]))
            ticket["observaciones"] = request.form.get("observaciones", ticket["observaciones"])
        ticket["actualizado"] = datetime.datetime.now().isoformat()
        save_tickets(tickets)
        flash("Ticket actualizado")
        return redirect(url_for("admin_ticket", ticket_id=ticket_id))

    _suc_num_at = ticket.get("sucursal", "").replace("Sucursal ", "").strip()
    return render_template(
        "admin_ticket.html",
        ticket=ticket,
        estados=ESTADOS,
        prioridades=PRIORIDADES,
        puede_derivar_ceyh=(ticket.get("asignado") == "CEYH" or ticket.get("asignado_proveedor") == "CEYH" or ticket.get("proveedor_nombre") == "CEYH") and ticket.get("asignado") != "Equipo Central",
        es_ceyh=es_ticket_ceyh(ticket),
        es_presupuesto=(ticket.get("categoria") == "Presupuestos"),
        tiene_abono_suc=bool(get_proveedor_abono_sucursal(_suc_num_at)),
    )


# --- Routes: Proveedores ---

@app.route("/admin/proveedores")
@admin_required
def admin_proveedores():
    vista = request.args.get("vista", "zona")
    buscar_suc = request.args.get("sucursal", "").replace("Sucursal ", "")
    filtro_zona = request.args.get("zona", "")

    # Build sucursal -> proveedores map
    suc_map = {}
    for p in PROVEEDORES:
        for s in p["sucursales"]:
            if s not in suc_map:
                suc_map[s] = []
            suc_map[s].append(p)

    # Filter by zone
    proveedores_filtrados = PROVEEDORES
    if filtro_zona:
        proveedores_filtrados = [p for p in PROVEEDORES if p["zona"] == filtro_zona]

    # Search by sucursal
    resultados_suc = []
    if buscar_suc:
        buscar_suc_padded = buscar_suc.zfill(3)
        for p in PROVEEDORES:
            for s in p["sucursales"]:
                if buscar_suc in s or buscar_suc_padded in s:
                    resultados_suc.append(p)
                    break

    return render_template(
        "admin_proveedores.html",
        proveedores=proveedores_filtrados,
        zonas=ZONAS,
        suc_map=suc_map,
        vista=vista,
        buscar_suc=buscar_suc,
        filtro_zona=filtro_zona,
        resultados_suc=resultados_suc,
        sucursales=SUCURSALES,
    )


# --- Routes: Inventario ---

@app.route("/admin/inventario")
@admin_required
def admin_inventario():
    if IS_CLOUD:
        return render_template("admin_inventario.html", inventario=[], total_ge=0, total_respondieron=0, total_sucursales=0, total_persianas=0, total_aires=0)
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "google_calendar"))
    from gauth import sheets as get_sheets

    SSID = "1nsWmQ1umlOoFLt9C3O1Uhi0SQp02JEQd7PX-btb4pm0"
    service = get_sheets()
    meta = service.spreadsheets().get(spreadsheetId=SSID).execute()
    sheet_names = [s["properties"]["title"] for s in meta["sheets"]]

    inventario = []
    for name in sheet_names:
        try:
            result = service.spreadsheets().values().get(
                spreadsheetId=SSID,
                range=f"'{name}'!H4:K4",
            ).execute()
            rows = result.get("values", [])
            if rows and any(str(c).strip() for c in rows[0]):
                r = rows[0]
                tiene_ge = r[0] if len(r) > 0 else ""
                modelo_ge = r[1] if len(r) > 1 else ""
                persianas = r[2] if len(r) > 2 else ""
                aires = r[3] if len(r) > 3 else ""
                if tiene_ge and tiene_ge not in ("¿Cuenta con grupo electrógeno?",):
                    inventario.append({
                        "sucursal": name,
                        "grupo_electrogeno": tiene_ge,
                        "modelo_ge": modelo_ge,
                        "persianas": persianas,
                        "aires": aires,
                    })
        except Exception:
            pass

    inventario.sort(key=lambda x: x["sucursal"])
    total_ge = sum(1 for i in inventario if i["grupo_electrogeno"] == "Sí")
    total_persianas = sum(int(i["persianas"]) for i in inventario if i["persianas"].isdigit())
    total_aires = sum(int(i["aires"]) for i in inventario if i["aires"].isdigit())

    return render_template(
        "admin_inventario.html",
        inventario=inventario,
        total_ge=total_ge,
        total_respondieron=len(inventario),
        total_sucursales=len(sheet_names),
        total_persianas=total_persianas,
        total_aires=total_aires,
    )


# --- Routes: Portal Proveedor ---

def prov_login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "prov_user" not in session:
            return redirect(url_for("prov_login"))
        return f(*args, **kwargs)
    return decorated


@app.route("/proveedor/login", methods=["GET", "POST"])
def prov_login():
    if request.method == "POST":
        user = request.form.get("usuario", "").lower().strip()
        pwd = request.form.get("password", "")
        if user in PROVEEDOR_USERS and PROVEEDOR_USERS[user]["password"] == pwd:
            session["prov_user"] = user
            session["prov_nombre"] = PROVEEDOR_USERS[user]["nombre"]
            return redirect(url_for("prov_panel"))
        flash("Usuario o contraseña incorrectos")
    return render_template("prov_login.html")


@app.route("/proveedor/logout", methods=["GET", "POST"])
def prov_logout():
    session.pop("prov_user", None)
    session.pop("prov_nombre", None)
    return redirect(url_for("prov_login"))


@app.route("/proveedor")
@prov_login_required
def prov_panel():
    tickets = load_tickets()
    prov_nombre = session.get("prov_nombre", "")
    jornadas_hoy = []
    mis_tickets = [t for t in tickets if t.get("asignado") == prov_nombre and t["estado"] not in ("Cerrado",)]
    pendientes_todo = [t for t in mis_tickets if t["estado"] not in ("Resuelto",)]
    trabajos_materiales = [t for t in pendientes_todo if t.get("tipo") == "trabajo_proveedor"]
    pendientes = [t for t in pendientes_todo if t.get("tipo") != "trabajo_proveedor"]
    resueltos = [t for t in mis_tickets if t["estado"] == "Resuelto"]

    # Notifications for provider
    notif_prov = []
    for t in tickets:
        if t.get("asignado") == prov_nombre:
            for n in t.get("notificaciones_prov", []):
                notif_prov.append({"ticket_id": t["id"], "sucursal": t["sucursal"], **n})
    notif_prov.sort(key=lambda x: x.get("fecha", ""), reverse=True)

    retiros_ceyh = []
    if prov_nombre == "CEYH":
        retiros_data = load_ceyh_retiros().get("retiros", [])
        for r in retiros_data:
            if r.get("estado") in ("Listo para retirar", "Retirado por CEYH"):
                retiros_ceyh.append(r)
        retiros_ceyh.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        jornadas = load_ceyh_jornadas().get("jornadas", [])
        hoy = datetime.date.today().isoformat()
        jornadas_hoy = [j for j in jornadas if j.get("fecha") == hoy]

    return render_template(
        "prov_panel.html",
        pendientes=pendientes,
        trabajos_materiales=trabajos_materiales,
        resueltos=resueltos,
        prioridades=PRIORIDADES,
        notificaciones=notif_prov,
        retiros_ceyh=retiros_ceyh,
        jornadas_hoy=jornadas_hoy,
    )


@app.route("/proveedor/ticket/<int:ticket_id>", methods=["GET", "POST"])
@prov_login_required
def prov_ticket(ticket_id):
    tickets = load_tickets()
    ticket = next((t for t in tickets if t["id"] == ticket_id), None)
    if not ticket:
        return "Ticket no encontrado", 404

    if request.method == "POST":
        accion = request.form.get("accion", "")
        prov_nombre = session.get("prov_nombre", "Proveedor")
        if "notas" not in ticket:
            ticket["notas"] = []

        etapa_labels = {
            "recibido": ("Recibido", "Abierto"),
            "planificado": ("Planificado", "En progreso"),
            "relevado": ("Relevado", "En progreso"),
            "en_progreso_prov": ("En progreso", "En progreso"),
            "esperando_materiales": ("Esperando materiales", "Pendiente"),
            "esperando_presupuesto": ("Esperando aprobacion de presupuesto", "Pendiente"),
            "hecho": ("Hecho", "Resuelto"),
            "en_camino": ("En camino", "En progreso"),
            "trabajo_iniciado": ("Trabajo iniciado", "En progreso"),
            "trabajo_terminado": ("Trabajo terminado", "Resuelto"),
        }

        if accion in etapa_labels:
            label, estado = etapa_labels[accion]
            ticket["etapa_prov"] = accion
            ticket["estado"] = estado

            # Save visit date if planificado
            nota_texto = f"Etapa: {label}"
            if accion == "planificado":
                fecha_visita = request.form.get("fecha_visita", "")
                if fecha_visita:
                    ticket["fecha_visita"] = fecha_visita
                    nota_texto = f"Visita planificada para {fecha_visita}"
                    # Create notification for sucursal
                    if "notificaciones" not in ticket:
                        ticket["notificaciones"] = []
                    ticket["notificaciones"].append({
                        "fecha": datetime.datetime.now().isoformat(),
                        "texto": f"{prov_nombre} visitara la sucursal el {fecha_visita}",
                        "leida": False,
                    })

            ticket["notas"].append({
                "autor": prov_nombre,
                "fecha": datetime.datetime.now().isoformat(),
                "texto": nota_texto,
            })

            # Si es un trabajo de proveedor vinculado a un pedido de materiales,
            # avisar al ticket origen (especialmente al terminar).
            if ticket.get("tipo") == "trabajo_proveedor" and ticket.get("origen_ticket_id"):
                origen = next((x for x in tickets if x["id"] == ticket["origen_ticket_id"]), None)
                if origen is not None:
                    if "notas" not in origen:
                        origen["notas"] = []
                    if accion == "trabajo_terminado":
                        origen_texto = f"{prov_nombre} marco el trabajo como TERMINADO (ticket #{ticket['id']})"
                    else:
                        origen_texto = f"{prov_nombre} actualizo el trabajo: {label} (ticket #{ticket['id']})"
                    origen["notas"].append({
                        "autor": "Sistema",
                        "fecha": datetime.datetime.now().isoformat(),
                        "texto": origen_texto,
                    })
                    origen["actualizado"] = datetime.datetime.now().isoformat()
        elif accion == "nota":
            nota = request.form.get("nota", "").strip()
            if nota:
                ticket["notas"].append({
                    "autor": prov_nombre,
                    "fecha": datetime.datetime.now().isoformat(),
                    "texto": nota,
                })
        elif accion == "foto_antes":
            f = request.files.get("foto")
            if f and f.filename:
                ext = Path(f.filename).suffix.lower()
                if ext in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
                    fname = f"{ticket_id}_antes_{uuid.uuid4().hex[:8]}{ext}"
                    f.save(str(UPLOADS_DIR / fname))
                    if "fotos_antes" not in ticket:
                        ticket["fotos_antes"] = []
                    ticket["fotos_antes"].append(fname)
                    ticket["notas"].append({
                        "autor": prov_nombre,
                        "fecha": datetime.datetime.now().isoformat(),
                        "texto": "Subio foto ANTES del trabajo",
                        "fotos": [fname],
                    })
        elif accion == "foto_despues":
            f = request.files.get("foto")
            if f and f.filename:
                ext = Path(f.filename).suffix.lower()
                if ext in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
                    fname = f"{ticket_id}_despues_{uuid.uuid4().hex[:8]}{ext}"
                    f.save(str(UPLOADS_DIR / fname))
                    if "fotos_despues" not in ticket:
                        ticket["fotos_despues"] = []
                    ticket["fotos_despues"].append(fname)
                    ticket["notas"].append({
                        "autor": prov_nombre,
                        "fecha": datetime.datetime.now().isoformat(),
                        "texto": "Subio foto DESPUES del trabajo",
                        "fotos": [fname],
                    })
        elif accion == "no_se_pudo":
            motivo = request.form.get("motivo", "").strip()
            if motivo:
                ticket["etapa_prov"] = "bloqueado"
                ticket["estado"] = "Pendiente"
                ticket["notas"].append({
                    "autor": prov_nombre,
                    "fecha": datetime.datetime.now().isoformat(),
                    "texto": f"NO SE PUDO REALIZAR: {motivo}",
                })
        elif accion == "presupuesto":
            detalle = request.form.get("detalle_presupuesto", "").strip()
            monto = request.form.get("monto_presupuesto", "")
            archivo = ""
            f = request.files.get("archivo_presupuesto")
            if f and f.filename:
                ext = Path(f.filename).suffix.lower()
                fname = f"{ticket_id}_ppto_{uuid.uuid4().hex[:8]}{ext}"
                f.save(str(UPLOADS_DIR / fname))
                archivo = fname
            if detalle:
                if "presupuestos" not in ticket:
                    ticket["presupuestos"] = []
                ticket["presupuestos"].append({
                    "autor": prov_nombre,
                    "fecha": datetime.datetime.now().isoformat(),
                    "detalle": detalle,
                    "monto": monto,
                    "archivo": archivo,
                })
                ticket["notas"].append({
                    "autor": prov_nombre,
                    "fecha": datetime.datetime.now().isoformat(),
                    "texto": f"Envio presupuesto adicional: ${monto} - {detalle[:80]}",
                })
        elif accion == "informe":
            informe_texto = request.form.get("informe", "").strip()
            archivo = ""
            f = request.files.get("archivo_informe")
            if f and f.filename:
                ext = Path(f.filename).suffix.lower()
                fname = f"{ticket_id}_informe_{uuid.uuid4().hex[:8]}{ext}"
                f.save(str(UPLOADS_DIR / fname))
                archivo = fname
            if informe_texto:
                if "informes" not in ticket:
                    ticket["informes"] = []
                ticket["informes"].append({
                    "autor": prov_nombre,
                    "fecha": datetime.datetime.now().isoformat(),
                    "texto": informe_texto,
                    "archivo": archivo,
                })
                ticket["notas"].append({
                    "autor": prov_nombre,
                    "fecha": datetime.datetime.now().isoformat(),
                    "texto": f"Envio informe: {informe_texto[:80]}...",
                })
        elif accion == "confirmar_retiro_ceyh":
            data = load_ceyh_retiros()
            rid = request.form.get("retiro_id", "").strip()
            retiro = next((r for r in data.get("retiros", []) if r.get("id") == rid and str(r.get("ticket_id")) == str(ticket_id)), None)
            if retiro:
                retiro["estado"] = "Retirado por CEYH"
                retiro["retirado_por"] = prov_nombre
                retiro["fecha_retiro"] = datetime.datetime.now().date().isoformat()
                retiro["confirmado_por_portal"] = True
                retiro["updated_at"] = datetime.datetime.now().isoformat()
                save_ceyh_retiros(data)

                ticket = _normalize_ceyh_ticket(ticket)
                ticket["requiere_materiales"] = True
                ticket["requiere_retiro_central"] = True
                ticket["estado_materiales"] = "Retirado"
                ticket["estado_retiro"] = "Retirado por CEYH"
                ticket["ultima_novedad_operativa"] = "CEYH confirmó retiro de materiales desde portal"
                ticket.setdefault("notas", []).append({
                    "autor": prov_nombre,
                    "fecha": datetime.datetime.now().isoformat(),
                    "texto": "Confirmó retiro de materiales en Dabra Central desde portal",
                })
        elif accion == "material_aplicado_ceyh":
            data = load_ceyh_retiros()
            rid = request.form.get("retiro_id", "").strip()
            retiro = next((r for r in data.get("retiros", []) if r.get("id") == rid and str(r.get("ticket_id")) == str(ticket_id)), None)
            if retiro:
                retiro["estado"] = "Material aplicado al trabajo"
                retiro["fecha_entrega"] = datetime.datetime.now().date().isoformat()
                retiro["updated_at"] = datetime.datetime.now().isoformat()
                save_ceyh_retiros(data)

                ticket = _normalize_ceyh_ticket(ticket)
                ticket["estado_materiales"] = "Aplicado"
                ticket["estado_retiro"] = "Material aplicado al trabajo"
                ticket["ultima_novedad_operativa"] = "CEYH marcó materiales como usados para ejecutar el ticket"
                ticket.setdefault("notas", []).append({
                    "autor": prov_nombre,
                    "fecha": datetime.datetime.now().isoformat(),
                    "texto": "Marcó materiales como aplicados al trabajo desde portal",
                })
        elif accion == "sobrante_ceyh":
            data = load_ceyh_retiros()
            rid = request.form.get("retiro_id", "").strip()
            destino = request.form.get("destino_sobrante", "").strip() or "Sobrante en sucursal"
            detalle = request.form.get("detalle_sobrante", "").strip()
            retiro = next((r for r in data.get("retiros", []) if r.get("id") == rid and str(r.get("ticket_id")) == str(ticket_id)), None)
            if retiro:
                retiro["estado"] = destino
                retiro["detalle_sobrante"] = detalle
                retiro["updated_at"] = datetime.datetime.now().isoformat()
                save_ceyh_retiros(data)

                ticket = _normalize_ceyh_ticket(ticket)
                ticket["estado_materiales"] = "Sobrante"
                ticket["estado_retiro"] = destino
                ticket["ultima_novedad_operativa"] = f"CEYH registró sobrante: {destino}"
                ticket.setdefault("notas", []).append({
                    "autor": prov_nombre,
                    "fecha": datetime.datetime.now().isoformat(),
                    "texto": f"Registró sobrante de materiales: {destino}" + (f" - {detalle}" if detalle else ""),
                })
        elif accion == "trabajo_continua_manana":
            motivo = request.form.get("motivo_continua", "").strip() or "Falta de materiales"
            ticket["etapa_prov"] = "continua_manana"
            ticket["estado"] = "Pendiente"
            ticket.setdefault("notas", []).append({
                "autor": prov_nombre,
                "fecha": datetime.datetime.now().isoformat(),
                "texto": f"Trabajo no terminado. Continúa al día siguiente: {motivo}",
            })

        ticket["actualizado"] = datetime.datetime.now().isoformat()
        save_tickets(tickets)
        flash("Actualizado")
        return redirect(url_for("prov_ticket", ticket_id=ticket_id))

    retiros_ticket = []
    if session.get("prov_nombre") == "CEYH":
        retiros_ticket = [r for r in load_ceyh_retiros().get("retiros", []) if str(r.get("ticket_id")) == str(ticket_id)]
        retiros_ticket.sort(key=lambda x: x.get("created_at", ""), reverse=True)

    return render_template("prov_ticket.html", ticket=ticket, prioridades=PRIORIDADES, retiros_ticket=retiros_ticket)


# --- Routes: Portal de Compras (Laura) ---

@app.route("/compras/login", methods=["GET", "POST"])
def compras_login():
    if request.method == "POST":
        user = request.form.get("usuario", "").lower().strip()
        pwd = request.form.get("password", "")
        if user in COMPRAS_USERS and COMPRAS_USERS[user]["password"] == pwd:
            session["compras_user"] = user
            session["compras_nombre"] = COMPRAS_USERS[user]["nombre"]
            return redirect(url_for("compras_panel"))
        flash("Usuario o contraseña incorrectos")
    return render_template("compras_login.html")


@app.route("/compras/logout", methods=["GET", "POST"])
def compras_logout():
    session.pop("compras_user", None)
    session.pop("compras_nombre", None)
    return redirect(url_for("compras_login"))


def _compras_envios_agrupados():
    """Arma la lista de envios de Compras agrupando movimientos por envio_id."""
    movs = load_movimientos().get("movimientos", [])
    envios = {}
    for m in movs:
        if m.get("area") != "compras" or m.get("tipo") != "egreso":
            continue
        eid = m.get("envio_id") or m.get("id")
        envio = envios.setdefault(eid, {
            "envio_id": eid,
            "fecha": m.get("fecha", ""),
            "sucursal": m.get("sucursal", ""),
            "usuario": m.get("nota", ""),
            "lineas": [],
            "total": 0.0,
            "total_unidades": 0,
        })
        envio["lineas"].append({
            "item": m.get("item", ""),
            "cantidad": int(m.get("cantidad", 0) or 0),
            "precio_unitario": float(m.get("precio_unitario", 0) or 0),
            "monto_imputado": float(m.get("monto_imputado", 0) or 0),
        })
        envio["total"] += float(m.get("monto_imputado", 0) or 0)
        envio["total_unidades"] += int(m.get("cantidad", 0) or 0)
    out = list(envios.values())
    out.sort(key=lambda e: e.get("fecha", ""), reverse=True)
    return out


@app.route("/compras")
@compras_login_required
def compras_panel():
    stock = load_stock()
    mi_stock = filtrar_stock_laura(stock)
    items = sorted(
        ((k, v.get("cantidad", 0), v.get("precio_unitario", 0.0)) for k, v in mi_stock.items()),
        key=lambda x: x[0],
    )
    total_unidades = sum(c for _, c, _ in items)
    valor_stock = sum(c * p for _, c, p in items)

    envios = _compras_envios_agrupados()
    mes_actual = datetime.datetime.now().strftime("%Y-%m")
    envios_mes = [e for e in envios if e.get("fecha", "").startswith(mes_actual)]
    sucursales_atendidas = len({e.get("sucursal", "") for e in envios if e.get("sucursal")})

    ultimos_envios = envios[:10]

    return render_template(
        "compras_panel.html",
        items=items,
        total_items=len(items),
        total_unidades=total_unidades,
        valor_stock=valor_stock,
        envios_mes_count=len(envios_mes),
        sucursales_atendidas=sucursales_atendidas,
        ultimos_envios=ultimos_envios,
    )


@app.route("/compras/stock")
@compras_login_required
def compras_stock():
    from categories_data import MATERIAL_CATEGORIAS, INSUMOS_COMPRAS_PREFIX

    stock = load_stock()
    mi_stock = filtrar_stock_laura(stock)
    items = sorted(
        ((k, v.get("cantidad", 0), v.get("precio_unitario", 0.0)) for k, v in mi_stock.items()),
        key=lambda x: x[0],
    )
    total_unidades = sum(c for _, c, _ in items)
    valor_stock = sum(c * p for _, c, p in items)

    # Subitems de la categoria de insumos de compras para el selector.
    sub_items = []
    for cat in MATERIAL_CATEGORIAS:
        if cat.get("nombre") == INSUMOS_COMPRAS_PREFIX:
            sub_items = list(cat.get("items", []))
            break

    # Stock por sucursal filtrado a insumos de compras
    stock_sucursales = {}
    for suc, items_suc in (stock.get("sucursales", {}) or {}).items():
        filtrados = {k: v for k, v in (items_suc or {}).items() if _es_insumo_compras(k)}
        if filtrados:
            stock_sucursales[suc] = filtrados

    return render_template(
        "compras_stock.html",
        items=items,
        total_items=len(items),
        total_unidades=total_unidades,
        valor_stock=valor_stock,
        sub_items=sub_items,
        prefix=INSUMOS_COMPRAS_PREFIX,
        stock_sucursales=stock_sucursales,
    )


@app.route("/compras/stock/add", methods=["POST"])
@compras_login_required
def compras_stock_add():
    from categories_data import INSUMOS_COMPRAS_PREFIX

    stock = load_stock()
    subitem = request.form.get("subitem", "").strip()
    item_libre = request.form.get("item_libre", "").strip()
    try:
        cantidad = int(request.form.get("cantidad", 0))
    except (ValueError, TypeError):
        cantidad = 0
    precio_raw = request.form.get("precio_unitario", "").strip().replace(",", ".")
    try:
        precio = float(precio_raw) if precio_raw else None
    except ValueError:
        precio = None

    nombre = subitem or item_libre
    if not nombre:
        flash("Seleccione o ingrese un insumo")
        return redirect(url_for("compras_stock"))
    item_key = f"{INSUMOS_COMPRAS_PREFIX} > {nombre}"

    if cantidad <= 0:
        flash("Cantidad invalida")
        return redirect(url_for("compras_stock"))

    actual = get_central_qty(stock, item_key)
    set_central_qty(stock, item_key, actual + cantidad, precio=precio)
    save_stock(stock)
    registrar_movimiento(
        item=item_key,
        tipo="ingreso",
        cantidad=cantidad,
        sucursal="Central Dabra",
        nota=f"Ingreso manual (Compras) por {session.get('compras_nombre', 'Laura')}",
        precio_unitario=precio,
        area="compras",
    )
    flash(f"Agregado: {cantidad}x {nombre}" + (f" a ${precio:,.2f}" if precio else ""))
    return redirect(url_for("compras_stock"))


@app.route("/compras/stock/precio", methods=["POST"])
@compras_login_required
def compras_stock_precio():
    stock = load_stock()
    item = request.form.get("item", "").strip()
    if not item or not _es_insumo_compras(item):
        flash("Item no valido")
        return redirect(url_for("compras_stock"))
    precio_raw = request.form.get("precio_unitario", "").strip().replace(",", ".")
    try:
        precio = float(precio_raw) if precio_raw else 0.0
    except ValueError:
        flash("Precio invalido")
        return redirect(url_for("compras_stock"))
    set_central_precio(stock, item, precio)
    save_stock(stock)
    flash(f"Precio actualizado: {item} → ${precio:,.2f}")
    return redirect(url_for("compras_stock"))


@app.route("/compras/envios")
@compras_login_required
def compras_envios():
    envios = _compras_envios_agrupados()
    filtro_suc = request.args.get("sucursal", "").strip()
    filtro_desde = request.args.get("desde", "").strip()
    filtro_hasta = request.args.get("hasta", "").strip()

    filtrados = envios
    if filtro_suc:
        filtrados = [e for e in filtrados if e.get("sucursal") == filtro_suc]
    if filtro_desde:
        filtrados = [e for e in filtrados if e.get("fecha", "")[:10] >= filtro_desde]
    if filtro_hasta:
        filtrados = [e for e in filtrados if e.get("fecha", "")[:10] <= filtro_hasta]

    sucursales_con_envios = sorted({e.get("sucursal", "") for e in envios if e.get("sucursal")})
    total_valor = sum(e.get("total", 0) for e in filtrados)

    return render_template(
        "compras_envios.html",
        envios=filtrados,
        total_envios=len(filtrados),
        total_valor=total_valor,
        sucursales=sucursales_con_envios,
        filtro_suc=filtro_suc,
        filtro_desde=filtro_desde,
        filtro_hasta=filtro_hasta,
    )


@app.route("/compras/envio", methods=["GET", "POST"])
@compras_login_required
def compras_envio_nuevo():
    stock = load_stock()
    mi_stock = filtrar_stock_laura(stock)

    if request.method == "POST":
        sucursal = request.form.get("sucursal", "").strip()
        if not sucursal:
            flash("Seleccione una sucursal destino")
            return redirect(url_for("compras_envio_nuevo"))

        item_keys = request.form.getlist("item_key[]")
        item_cants = request.form.getlist("item_cantidad[]")

        # Construir lineas validas (item + cantidad > 0)
        lineas = []
        for idx, k in enumerate(item_keys):
            k = (k or "").strip()
            if not k or not _es_insumo_compras(k):
                continue
            try:
                cant = int(item_cants[idx]) if idx < len(item_cants) and item_cants[idx] else 0
            except (ValueError, IndexError):
                cant = 0
            if cant <= 0:
                continue
            lineas.append((k, cant))

        if not lineas:
            flash("Agregue al menos un item con cantidad > 0")
            return redirect(url_for("compras_envio_nuevo"))

        # Validar stock disponible antes de hacer cambios
        for k, cant in lineas:
            disponible = get_central_qty(stock, k)
            if cant > disponible:
                flash(f"Stock insuficiente para '{k}': hay {disponible}, pide {cant}")
                return redirect(url_for("compras_envio_nuevo"))

        envio_id = uuid.uuid4().hex[:12]
        usuario = session.get("compras_nombre", "Laura")

        # Asegurar slot en sucursales
        suc_store = stock.setdefault("sucursales", {}).setdefault(sucursal, {})

        total_valor = 0.0
        resumen = []
        for k, cant in lineas:
            precio_unit = _get_precio_historico(k) or get_central_precio(stock, k)
            # Descontar central
            disponible = get_central_qty(stock, k)
            set_central_qty(stock, k, disponible - cant)
            # Sumar en sucursal (int simple)
            suc_store[k] = int(suc_store.get(k, 0) or 0) + cant

            monto = round(cant * precio_unit, 2)
            total_valor += monto
            resumen.append(f"{cant}x {k}")

            registrar_movimiento(
                item=k,
                tipo="egreso",
                cantidad=cant,
                sucursal=sucursal,
                nota=f"Envio de Compras #{envio_id} a {sucursal} por {usuario}",
                monto_imputado=monto,
                precio_unitario=precio_unit,
                area="compras",
                envio_id=envio_id,
            )
            registrar_movimiento(
                item=k,
                tipo="ingreso",
                cantidad=cant,
                sucursal=sucursal,
                nota=f"Recepcion envio Compras #{envio_id} desde Central",
                monto_imputado=monto,
                precio_unitario=precio_unit,
                area="compras",
                envio_id=envio_id,
            )

        save_stock(stock)
        flash(f"Envio registrado a {sucursal} - {len(lineas)} items - ${total_valor:,.2f}")
        return redirect(url_for("compras_envios"))

    # GET: lista de items con stock > 0
    items_disponibles = sorted(
        (
            (k, v.get("cantidad", 0), v.get("precio_unitario", 0.0))
            for k, v in mi_stock.items()
            if v.get("cantidad", 0) > 0
        ),
        key=lambda x: x[0],
    )
    return render_template(
        "compras_envio_nuevo.html",
        items=items_disponibles,
        sucursales=SUCURSALES,
    )


@app.route("/compras/comprobantes")
@compras_login_required
def compras_comprobantes():
    data = load_comprobantes()
    comprobantes = [
        c for c in data.get("comprobantes", []) if c.get("area") == "compras"
    ]
    filtro_desde = request.args.get("desde", "").strip()
    filtro_hasta = request.args.get("hasta", "").strip()
    filtro_proveedor = request.args.get("proveedor", "").strip().lower()

    filtrados = comprobantes
    if filtro_desde:
        filtrados = [c for c in filtrados if c.get("fecha", "") >= filtro_desde]
    if filtro_hasta:
        filtrados = [c for c in filtrados if c.get("fecha", "") <= filtro_hasta]
    if filtro_proveedor:
        filtrados = [c for c in filtrados if filtro_proveedor in (c.get("proveedor", "") or "").lower()]

    filtrados.sort(key=lambda c: c.get("fecha", ""), reverse=True)

    total_monto = sum(float(c.get("monto", 0) or 0) for c in filtrados)
    proveedores_unicos = sorted({c.get("proveedor", "") for c in comprobantes if c.get("proveedor")})

    # Subitems para cargar asociando items a la factura
    from categories_data import MATERIAL_CATEGORIAS, INSUMOS_COMPRAS_PREFIX
    sub_items = []
    for cat in MATERIAL_CATEGORIAS:
        if cat.get("nombre") == INSUMOS_COMPRAS_PREFIX:
            sub_items = list(cat.get("items", []))
            break

    return render_template(
        "compras_comprobantes.html",
        comprobantes=filtrados,
        total_monto=total_monto,
        proveedores_unicos=proveedores_unicos,
        filtro_desde=filtro_desde,
        filtro_hasta=filtro_hasta,
        filtro_proveedor=request.args.get("proveedor", "").strip(),
        sub_items=sub_items,
        prefix=INSUMOS_COMPRAS_PREFIX,
    )


@app.route("/compras/comprobantes/nuevo", methods=["POST"])
@compras_login_required
def compras_comprobantes_nuevo():
    from categories_data import INSUMOS_COMPRAS_PREFIX

    data = load_comprobantes()
    numero = request.form.get("numero", "").strip()
    fecha = request.form.get("fecha", "").strip()
    proveedor = request.form.get("proveedor", "").strip()
    monto_raw = request.form.get("monto", "").strip().replace(",", ".")
    descripcion = request.form.get("descripcion", "").strip()

    if not numero or not fecha or not proveedor:
        flash("Complete numero, fecha y proveedor")
        return redirect(url_for("compras_comprobantes"))

    try:
        monto = float(monto_raw) if monto_raw else 0.0
    except ValueError:
        monto = 0.0

    archivo = ""
    f = request.files.get("archivo")
    if f and f.filename:
        ext = Path(f.filename).suffix.lower()
        if ext in COMPROBANTE_EXTENSIONES:
            fname = f"compras_{uuid.uuid4().hex[:10]}{ext}"
            f.save(str(COMPROBANTES_DIR / fname))
            archivo = fname
        else:
            flash("Formato no permitido (solo PDF, JPG, PNG)")
            return redirect(url_for("compras_comprobantes"))

    # Items asociados (opcional): suman al stock e impactan precio.
    items_factura = []
    item_names = request.form.getlist("item_nombre[]")
    item_cants = request.form.getlist("item_cantidad[]")
    item_precios = request.form.getlist("item_precio[]")
    stock_data = None
    for idx, nombre in enumerate(item_names):
        nombre = (nombre or "").strip()
        if not nombre:
            continue
        try:
            cant = int(item_cants[idx]) if idx < len(item_cants) and item_cants[idx] else 0
        except (ValueError, IndexError):
            cant = 0
        try:
            precio = float((item_precios[idx] if idx < len(item_precios) else "0").replace(",", ".")) if idx < len(item_precios) and item_precios[idx] else 0.0
        except (ValueError, IndexError):
            precio = 0.0
        if cant <= 0 and precio <= 0:
            continue
        item_key = f"{INSUMOS_COMPRAS_PREFIX} > {nombre}"
        items_factura.append({"item": item_key, "cantidad": cant, "precio_unitario": precio})
        if cant > 0:
            if stock_data is None:
                stock_data = load_stock()
            actual = get_central_qty(stock_data, item_key)
            set_central_qty(stock_data, item_key, actual + cant, precio=precio if precio > 0 else None)
            registrar_movimiento(
                item=item_key,
                tipo="ingreso",
                cantidad=cant,
                sucursal="Central Dabra",
                nota=f"Ingreso por factura Compras {numero} ({proveedor})",
                precio_unitario=precio if precio > 0 else None,
                area="compras",
            )
    if stock_data is not None:
        save_stock(stock_data)

    comprobante = {
        "id": uuid.uuid4().hex[:12],
        "tipo": "factura",
        "area": "compras",
        "numero": numero,
        "fecha": fecha,
        "proveedor": proveedor,
        "monto": monto,
        "descripcion": descripcion,
        "archivo": archivo,
        "items_factura": items_factura,
        "created_at": datetime.datetime.now().isoformat(),
        "cargado_por": session.get("compras_nombre", "Laura"),
    }
    data.setdefault("comprobantes", []).append(comprobante)
    save_comprobantes(data)
    flash(f"Factura registrada: #{numero}" + (f" - {len(items_factura)} items" if items_factura else ""))
    return redirect(url_for("compras_comprobantes"))


# --- Routes: Portal Equipo de Mantenimiento Central (Hector y Jose) ---

def _tickets_equipo(tickets):
    """Filtra tickets que deben ejecutar el Equipo Central."""
    return [
        t for t in tickets
        if (t.get("siguiente_paso") == "personal_mantenimiento" or t.get("asignado") == "Equipo Central")
        and t.get("estado") != "Cerrado"
    ]


@app.route("/equipo/login", methods=["GET", "POST"])
def equipo_login():
    if request.method == "POST":
        user = request.form.get("usuario", "").lower().strip()
        pwd = request.form.get("password", "")
        if user in EQUIPO_USERS and EQUIPO_USERS[user]["password"] == pwd:
            session["equipo_user"] = user
            session["equipo_nombre"] = EQUIPO_USERS[user]["nombre"]
            return redirect(url_for("equipo_panel"))
        flash("Usuario o contraseña incorrectos")
    return render_template("equipo_login.html")


@app.route("/equipo/logout", methods=["GET", "POST"])
def equipo_logout():
    session.pop("equipo_user", None)
    session.pop("equipo_nombre", None)
    return redirect(url_for("equipo_login"))


@app.route("/equipo")
@equipo_login_required
def equipo_panel():
    tickets = load_tickets()
    mis = _tickets_equipo(tickets)
    vehiculos = [_enrich_vehiculo(v) for v in load_vehiculos_equipo().get("vehiculos", [])]

    etapa_default = {"pendiente": [], "en_progreso": [], "terminados": []}
    etapa_default["pendiente"] = [
        t for t in mis if t.get("etapa_equipo", "asignado") in ("asignado", "")
    ]
    etapa_default["en_progreso"] = [
        t for t in mis if t.get("etapa_equipo") in ("en_camino", "iniciado")
    ]
    mes_actual = datetime.datetime.now().strftime("%Y-%m")
    etapa_default["terminados"] = [
        t for t in tickets
        if t.get("siguiente_paso") == "personal_mantenimiento"
        and t.get("etapa_equipo") == "terminado"
        and (t.get("actualizado", "")[:7] == mes_actual)
    ]

    # Ordenar pendientes por prioridad y fecha
    pendientes = sorted(
        etapa_default["pendiente"],
        key=lambda t: (t.get("prioridad", 4), t.get("creado", "")),
    )
    en_progreso = sorted(
        etapa_default["en_progreso"],
        key=lambda t: (t.get("prioridad", 4), t.get("creado", "")),
    )
    terminados_mes = sorted(
        etapa_default["terminados"],
        key=lambda t: t.get("actualizado", ""),
        reverse=True,
    )

    return render_template(
        "equipo_panel.html",
        pendientes=pendientes,
        en_progreso=en_progreso,
        terminados_mes=terminados_mes,
        prioridades=PRIORIDADES,
        vehiculos=vehiculos,
    )


def _get_ticket_equipo(ticket_id, tickets):
    """Busca un ticket que pertenezca al equipo. Devuelve None si no aplica."""
    ticket = next((t for t in tickets if t["id"] == ticket_id), None)
    if not ticket:
        return None
    if ticket.get("siguiente_paso") != "personal_mantenimiento":
        return None
    return ticket


@app.route("/equipo/ticket/<int:ticket_id>")
@equipo_login_required
def equipo_ticket(ticket_id):
    tickets = load_tickets()
    ticket = _get_ticket_equipo(ticket_id, tickets)
    if not ticket:
        return render_template("error.html", mensaje="Ticket no disponible para el equipo."), 404
    return render_template(
        "equipo_ticket.html",
        ticket=ticket,
        prioridades=PRIORIDADES,
    )


@app.route("/equipo/ticket/<int:ticket_id>/etapa", methods=["POST"])
@equipo_login_required
def equipo_ticket_etapa(ticket_id):
    tickets = load_tickets()
    ticket = _get_ticket_equipo(ticket_id, tickets)
    if not ticket:
        return render_template("error.html", mensaje="Ticket no disponible para el equipo."), 404

    nueva = request.form.get("etapa", "").strip()
    etapas_validas = {"asignado", "en_camino", "iniciado", "terminado"}
    if nueva not in etapas_validas:
        flash("Etapa invalida")
        return redirect(url_for("equipo_ticket", ticket_id=ticket_id))

    autor = session.get("equipo_nombre") or session.get("nombre") or "Equipo Central"
    labels = {
        "asignado": ("Asignado", "Abierto"),
        "en_camino": ("En camino", "En progreso"),
        "iniciado": ("Trabajo iniciado", "En progreso"),
        "terminado": ("Trabajo terminado", "Resuelto"),
    }
    label, estado = labels[nueva]
    ticket["etapa_equipo"] = nueva
    ticket["estado"] = estado
    ticket.setdefault("notas", []).append({
        "autor": autor,
        "fecha": datetime.datetime.now().isoformat(),
        "texto": f"Etapa equipo: {label}",
    })
    ticket["actualizado"] = datetime.datetime.now().isoformat()
    save_tickets(tickets)
    flash(f"Etapa actualizada: {label}")
    return redirect(url_for("equipo_ticket", ticket_id=ticket_id))


@app.route("/equipo/ticket/<int:ticket_id>/foto", methods=["POST"])
@equipo_login_required
def equipo_ticket_foto(ticket_id):
    tickets = load_tickets()
    ticket = _get_ticket_equipo(ticket_id, tickets)
    if not ticket:
        return render_template("error.html", mensaje="Ticket no disponible para el equipo."), 404

    autor = session.get("equipo_nombre") or session.get("nombre") or "Equipo Central"
    f = request.files.get("foto")
    if not f or not f.filename:
        flash("Sin foto")
        return redirect(url_for("equipo_ticket", ticket_id=ticket_id))

    ext = Path(f.filename).suffix.lower()
    if ext not in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
        flash("Formato no soportado")
        return redirect(url_for("equipo_ticket", ticket_id=ticket_id))

    fname = f"{ticket_id}_trabajo_{uuid.uuid4().hex[:8]}{ext}"
    f.save(str(TRABAJOS_DIR / fname))
    rel = f"trabajos/{fname}"
    ticket.setdefault("fotos_trabajo", []).append(rel)
    ticket.setdefault("notas", []).append({
        "autor": autor,
        "fecha": datetime.datetime.now().isoformat(),
        "texto": "Subio foto del trabajo",
        "fotos": [rel],
    })
    ticket["actualizado"] = datetime.datetime.now().isoformat()
    save_tickets(tickets)
    flash("Foto subida")
    return redirect(url_for("equipo_ticket", ticket_id=ticket_id))


@app.route("/equipo/ticket/<int:ticket_id>/nota", methods=["POST"])
@equipo_login_required
def equipo_ticket_nota(ticket_id):
    tickets = load_tickets()
    ticket = _get_ticket_equipo(ticket_id, tickets)
    if not ticket:
        return render_template("error.html", mensaje="Ticket no disponible para el equipo."), 404

    autor = session.get("equipo_nombre") or session.get("nombre") or "Equipo Central"
    texto = request.form.get("nota", "").strip()
    if not texto:
        flash("Nota vacia")
        return redirect(url_for("equipo_ticket", ticket_id=ticket_id))

    ticket.setdefault("notas", []).append({
        "autor": autor,
        "fecha": datetime.datetime.now().isoformat(),
        "texto": texto,
    })
    ticket["actualizado"] = datetime.datetime.now().isoformat()
    save_tickets(tickets)
    flash("Nota agregada")
    return redirect(url_for("equipo_ticket", ticket_id=ticket_id))


@app.route("/equipo/stock")
@equipo_login_required
def equipo_stock():
    stock = load_stock()
    central = stock.get("central", {}) or {}
    items = sorted(
        ((k, v.get("cantidad", 0), v.get("precio_unitario", 0.0)) for k, v in central.items()),
        key=lambda x: x[0],
    )
    total_unidades = sum(c for _, c, _ in items)
    valor_stock = sum(c * p for _, c, p in items)
    return render_template(
        "equipo_stock.html",
        items=items,
        total_items=len(items),
        total_unidades=total_unidades,
        valor_stock=valor_stock,
    )


@app.route("/equipo/vehiculos", methods=["GET", "POST"])
@equipo_login_required
def equipo_vehiculos():
    data = load_vehiculos_equipo()
    if request.method == "POST":
        patente = request.form.get("patente", "").strip().upper()
        if not patente:
            flash("Ingrese patente")
            return redirect(url_for("equipo_vehiculos"))
        nuevo = {
            "id": uuid.uuid4().hex[:12],
            "patente": patente,
            "marca": request.form.get("marca", "").strip(),
            "modelo": request.form.get("modelo", "").strip(),
            "anio": request.form.get("anio", "").strip(),
            "seguro_vencimiento": request.form.get("seguro_vencimiento", "").strip(),
            "vtv_vencimiento": request.form.get("vtv_vencimiento", "").strip(),
            "observaciones": request.form.get("observaciones", "").strip(),
            "informes": [],
            "created_at": datetime.datetime.now().isoformat(),
            "cargado_por": session.get("equipo_nombre") or session.get("nombre") or "Equipo Central",
        }
        data.setdefault("vehiculos", []).append(nuevo)
        save_vehiculos_equipo(data)
        flash("Vehículo cargado")
        return redirect(url_for("equipo_vehiculos"))

    items = [_enrich_vehiculo(v) for v in data.get("vehiculos", [])]
    items.sort(key=lambda x: (x.get("estado_seguro") == "vencido" or x.get("estado_vtv") == "vencido", x.get("patente", "")), reverse=True)
    return render_template("equipo_vehiculos.html", vehiculos=items)


@app.route("/equipo/vehiculos/<vid>/informe", methods=["POST"])
@equipo_login_required
def equipo_vehiculo_informe(vid):
    data = load_vehiculos_equipo()
    vehiculo = next((v for v in data.get("vehiculos", []) if v.get("id") == vid), None)
    if not vehiculo:
        return render_template("error.html", mensaje="Vehículo no encontrado"), 404
    f = request.files.get("archivo")
    if not f or not f.filename:
        flash("Sin archivo")
        return redirect(url_for("equipo_vehiculos"))
    ext = Path(f.filename).suffix.lower()
    if ext not in (".pdf", ".jpg", ".jpeg", ".png", ".webp"):
        flash("Formato no soportado")
        return redirect(url_for("equipo_vehiculos"))
    fname = f"vehiculo_{vehiculo['patente']}_{uuid.uuid4().hex[:8]}{ext}"
    f.save(str(TRABAJOS_DIR / fname))
    vehiculo.setdefault("informes", []).append({
        "archivo": fname,
        "nombre": f.filename,
        "fecha": datetime.datetime.now().isoformat(),
        "detalle": request.form.get("detalle", "").strip(),
    })
    save_vehiculos_equipo(data)
    flash("Informe adjuntado")
    return redirect(url_for("equipo_vehiculos"))


@app.route("/uploads/trabajos/<filename>")
@any_session_required
def serve_trabajo(filename):
    return send_from_directory(str(TRABAJOS_DIR), filename)


# --- Routes: Ficha Sucursal ---

@app.route("/admin/sucursal/<suc_num>")
@admin_required
def admin_sucursal(suc_num):
    from sucursales_data import SUCURSALES_INFO

    # Sucursal info
    info = SUCURSALES_INFO.get(suc_num, {})
    suc_name = f"Sucursal {suc_num}"

    # Tickets
    tickets = load_tickets()
    suc_tickets = [t for t in tickets if t["sucursal"] == suc_name]
    activos = [t for t in suc_tickets if t["estado"] not in ("Resuelto", "Cerrado")]
    cerrados = [t for t in suc_tickets if t["estado"] in ("Resuelto", "Cerrado")]
    presupuestos_data = load_presupuestos().get("presupuestos", [])
    presupuestos_sucursal = [p for p in presupuestos_data if p.get("sucursal") == suc_name]
    presupuestos_sucursal.sort(key=lambda x: x.get("fecha_carga", ""), reverse=True)

    # Proveedores que cubren esta sucursal
    mis_proveedores = []
    for p in PROVEEDORES:
        for s in p["sucursales"]:
            if s == suc_num or s == suc_num.lstrip("0"):
                if p.get("tipo") == "Fumigaciones" and p.get("mostrar_sucursal") is False:
                    continue
                mis_proveedores.append(p)
                break

    # Inventario from Google Sheets
    inventario = {}
    try:
        import sys

        from gauth import sheets as get_sheets
        SSID = "1nsWmQ1umlOoFLt9C3O1Uhi0SQp02JEQd7PX-btb4pm0"
        service = get_sheets()
        result = service.spreadsheets().values().get(
            spreadsheetId=SSID,
            range=f"'{suc_name}'!H4:K4",
        ).execute()
        rows = result.get("values", [])
        if rows and rows[0]:
            r = rows[0]
            inventario = {
                "grupo_electrogeno": r[0] if len(r) > 0 else "",
                "modelo_ge": r[1] if len(r) > 1 else "",
                "persianas": r[2] if len(r) > 2 else "",
                "aires": r[3] if len(r) > 3 else "",
            }
    except Exception:
        pass

    return render_template(
        "admin_sucursal.html",
        suc_num=suc_num,
        suc_name=suc_name,
        info=info,
        activos=activos,
        cerrados=cerrados,
        presupuestos_sucursal=presupuestos_sucursal[:20],
        mis_proveedores=mis_proveedores,
        inventario=inventario,
        prioridades=PRIORIDADES,
    )


# --- Routes: Mapa ---

@app.route("/admin/mapa")
@admin_required
def admin_mapa():
    from sucursales_data import SUCURSALES_INFO
    tickets = load_tickets()

    # Count tickets per sucursal
    from collections import Counter
    ticket_counts = Counter(t["sucursal"].replace("Sucursal ", "") for t in tickets if t["estado"] not in ("Resuelto", "Cerrado"))

    sucursales_mapa = []
    for num, info in SUCURSALES_INFO.items():
        sucursales_mapa.append({
            "num": num,
            "marca": info["marca"],
            "tienda": info["tienda"],
            "ciudad": info["ciudad"],
            "provincia": info["provincia"],
            "direccion": info["direccion"],
            "lat": info["lat"],
            "lng": info["lng"],
            "tickets": ticket_counts.get(num, 0),
        })

    return render_template("admin_mapa.html", sucursales=sucursales_mapa)


# --- Routes: Reporte semanal ---

@app.route("/admin/reporte", methods=["POST"])
@admin_required
def admin_reporte():
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "google_calendar"))

    tickets = load_tickets()
    now = datetime.datetime.now()

    # Stats
    total = len(tickets)
    nuevos = sum(1 for t in tickets if t["estado"] == "Nuevo")
    abiertos = sum(1 for t in tickets if t["estado"] == "Abierto")
    en_progreso = sum(1 for t in tickets if t["estado"] == "En progreso")
    pendientes = sum(1 for t in tickets if t["estado"] == "Pendiente")
    resueltos = sum(1 for t in tickets if t["estado"] == "Resuelto")

    # Tickets this week
    semana = [t for t in tickets if (now - datetime.datetime.fromisoformat(t["creado"])).days <= 7]

    # Urgentes (prioridad 1)
    urgentes = [t for t in tickets if t["prioridad"] == 1 and t["estado"] not in ("Resuelto", "Cerrado")]

    # Alertas (> 5 meses)
    alertas = []
    for t in tickets:
        if t["estado"] not in ("Resuelto", "Cerrado"):
            try:
                age = (now - datetime.datetime.fromisoformat(t["creado"])).days
                if age > 150:
                    alertas.append({"ticket": t, "dias": age})
            except (ValueError, KeyError):
                pass

    # Build HTML email
    html = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; background: #111; color: #e2e8f0; padding: 24px; border-radius: 12px;">
        <div style="text-align: center; padding: 16px; border-bottom: 2px solid #e63946;">
            <h1 style="color: #e63946; margin: 0;">TECMAN</h1>
            <p style="color: #64748b; margin: 4px 0 0;">Reporte Semanal - {now.strftime('%d/%m/%Y')}</p>
        </div>

        <h2 style="color: #fff; margin-top: 24px;">Resumen General</h2>
        <table style="width: 100%; border-collapse: collapse; margin: 12px 0;">
            <tr><td style="padding: 8px; color: #94a3b8;">Total tickets</td><td style="padding: 8px; font-weight: 700; color: #fff; text-align: right;">{total}</td></tr>
            <tr style="background: rgba(255,255,255,0.03);"><td style="padding: 8px; color: #94a3b8;">Nuevos</td><td style="padding: 8px; font-weight: 700; color: #38bdf8; text-align: right;">{nuevos}</td></tr>
            <tr><td style="padding: 8px; color: #94a3b8;">Abiertos</td><td style="padding: 8px; font-weight: 700; color: #fbbf24; text-align: right;">{abiertos}</td></tr>
            <tr style="background: rgba(255,255,255,0.03);"><td style="padding: 8px; color: #94a3b8;">En progreso</td><td style="padding: 8px; font-weight: 700; color: #a78bfa; text-align: right;">{en_progreso}</td></tr>
            <tr><td style="padding: 8px; color: #94a3b8;">Pendientes</td><td style="padding: 8px; font-weight: 700; color: #f59e0b; text-align: right;">{pendientes}</td></tr>
            <tr style="background: rgba(255,255,255,0.03);"><td style="padding: 8px; color: #94a3b8;">Resueltos</td><td style="padding: 8px; font-weight: 700; color: #34d399; text-align: right;">{resueltos}</td></tr>
        </table>

        <h2 style="color: #fff; margin-top: 24px;">Tickets esta semana ({len(semana)})</h2>
        <table style="width: 100%; border-collapse: collapse; margin: 12px 0;">
            <tr style="border-bottom: 1px solid #333;"><th style="padding: 6px; color: #64748b; text-align: left; font-size: 11px;">#</th><th style="padding: 6px; color: #64748b; text-align: left; font-size: 11px;">Sucursal</th><th style="padding: 6px; color: #64748b; text-align: left; font-size: 11px;">Problema</th><th style="padding: 6px; color: #64748b; text-align: left; font-size: 11px;">Estado</th></tr>
    """
    for t in semana[:15]:
        html += f"""<tr style="border-bottom: 1px solid #1a1a1a;"><td style="padding: 6px; color: #e63946; font-weight: 700;">{t['id']}</td><td style="padding: 6px; font-size: 13px;">{t['sucursal'].replace('Sucursal ', 'Suc ')}</td><td style="padding: 6px; font-size: 13px;">{t['subcategoria']}</td><td style="padding: 6px; font-size: 13px;">{t['estado']}</td></tr>"""

    if urgentes:
        html += f"""
        </table>
        <h2 style="color: #f87171; margin-top: 24px;">Tickets Urgentes ({len(urgentes)})</h2>
        <table style="width: 100%; border-collapse: collapse; margin: 12px 0;">
        """
        for t in urgentes:
            html += f"""<tr style="border-bottom: 1px solid #1a1a1a; background: rgba(239,68,68,0.05);"><td style="padding: 8px; color: #f87171; font-weight: 700;">#{t['id']}</td><td style="padding: 8px;">{t['sucursal']}</td><td style="padding: 8px;">{t['subcategoria']}</td></tr>"""

    if alertas:
        html += f"""
        </table>
        <h2 style="color: #f59e0b; margin-top: 24px;">Alertas: {len(alertas)} tickets con mas de 5 meses</h2>
        <table style="width: 100%; border-collapse: collapse; margin: 12px 0;">
        """
        for a in sorted(alertas, key=lambda x: -x["dias"])[:10]:
            t = a["ticket"]
            html += f"""<tr style="border-bottom: 1px solid #1a1a1a;"><td style="padding: 6px; color: #f59e0b;">#{t['id']}</td><td style="padding: 6px;">{t['sucursal'].replace('Sucursal ', 'Suc ')}</td><td style="padding: 6px;">{t['subcategoria']}</td><td style="padding: 6px; color: #f87171; font-weight: 700;">{a['dias']}d</td></tr>"""

    html += """
        </table>
        <div style="text-align: center; margin-top: 24px; padding-top: 16px; border-top: 1px solid #222;">
            <p style="color: #333; font-size: 11px;">Generado por Tecman - Grupo Dabra</p>
        </div>
    </div>
    """

    try:
        _smtp_send("agustintomasbrahim@gmail.com", f"Tecman - Reporte Semanal {now.strftime('%d/%m/%Y')}", html)
        flash("Reporte enviado a agustintomasbrahim@gmail.com")
    except Exception as e:
        flash(f"Error al enviar: {str(e)}")

    return redirect(url_for("admin_panel", vista="dashboard"))


# --- Routes: Buscador ---

@app.route("/admin/buscar")
@admin_required
def admin_buscar():
    q = request.args.get("q", "").strip().lower()
    modulo = request.args.get("modulo", "todo").strip().lower()
    tickets = load_tickets()
    resultados = []
    resultados_presupuestos = []
    resultados_ceyh = []
    resultados_permisos = []
    resultados_habilitaciones = []
    resultados_matafuegos = []
    resultados_comprobantes = []

    def _match(*vals):
        texto = " ".join(str(v or "") for v in vals).lower()
        return q and q in texto

    if q:
        if modulo in ("todo", "tickets"):
            for t in tickets:
                notas = " ".join((n.get("texto", "") for n in t.get("notas", [])))
                if _match(t.get("id"), t.get("sucursal"), t.get("descripcion"), t.get("subcategoria"), t.get("categoria"), t.get("asignado"), t.get("observaciones"), t.get("solicitante"), notas):
                    resultados.append(t)

        if modulo in ("todo", "presupuestos"):
            for p in load_presupuestos().get("presupuestos", []):
                if _match(p.get("id"), p.get("ticket_id"), p.get("sucursal"), p.get("categoria"), p.get("subcategoria"), p.get("proveedor"), p.get("descripcion"), p.get("observacion_interna"), p.get("monto")):
                    resultados_presupuestos.append(p)

        if modulo in ("todo", "ceyh"):
            for t in tickets:
                if not es_ticket_ceyh(t):
                    continue
                t = _normalize_ceyh_ticket(t)
                if _match(t.get("id"), t.get("sucursal"), t.get("subcategoria"), t.get("cuadrilla_ceyh"), t.get("camioneta_ceyh"), t.get("estado_operativo_ceyh"), t.get("estado_materiales"), t.get("estado_retiro"), t.get("proxima_accion"), t.get("ultima_novedad_operativa")):
                    resultados_ceyh.append({"tipo": "ticket", **t})
            for r in load_ceyh_retiros().get("retiros", []):
                if _match(r.get("ticket_id"), r.get("sucursal"), r.get("materiales"), r.get("estado"), r.get("retirado_por"), r.get("observaciones")):
                    resultados_ceyh.append({"tipo": "retiro", **r})
            for j in load_ceyh_jornadas().get("jornadas", []):
                planif = " ".join(f"{x.get('ticket_id')} {x.get('sucursal')} {x.get('tipo')}" for x in j.get("planificados", []))
                urgs = " ".join(f"{x.get('ticket_id')} {x.get('sucursal')} {x.get('tipo')}" for x in j.get("urgencias", []))
                if _match(j.get("fecha"), j.get("camioneta"), j.get("cuadrilla"), j.get("observaciones"), planif, urgs):
                    resultados_ceyh.append({"tipo": "jornada", **j})

        if modulo in ("todo", "permisos"):
            for p in load_permisos().get("permisos", []):
                sucursales_txt = " ".join((s.get("sucursal", "") for s in p.get("sucursales", [])))
                if _match(p.get("id"), p.get("sucursal"), sucursales_txt, p.get("proveedor"), p.get("tipo_documento"), p.get("periodo"), p.get("comentario")):
                    resultados_permisos.append(p)

        if modulo in ("todo", "habilitaciones"):
            for h in load_habilitaciones().get("habilitaciones", []):
                if _match(h.get("id"), h.get("sucursal"), h.get("sucursal_num"), h.get("tramite"), h.get("estado"), h.get("comentario"), h.get("archivo_nombre")):
                    resultados_habilitaciones.append(h)

        if modulo in ("todo", "matafuegos"):
            for m in load_matafuegos().get("matafuegos", []):
                if _match(m.get("sucursal"), m.get("sucursal_num"), m.get("tipo"), m.get("sector"), m.get("estado"), m.get("vencimiento"), m.get("observaciones")):
                    resultados_matafuegos.append(m)

        if modulo in ("todo", "comprobantes"):
            for c in load_comprobantes().get("comprobantes", []):
                items_txt = " ".join(f"{i.get('item', '')} {i.get('cantidad', '')}" for i in c.get("items", []))
                if _match(c.get("id"), c.get("tipo"), c.get("numero"), c.get("proveedor"), c.get("sucursal"), c.get("comentario"), items_txt):
                    resultados_comprobantes.append(c)

    return render_template(
        "admin_buscar.html",
        q=q,
        modulo=modulo,
        resultados=resultados,
        resultados_presupuestos=resultados_presupuestos,
        resultados_ceyh=resultados_ceyh,
        resultados_permisos=resultados_permisos,
        resultados_habilitaciones=resultados_habilitaciones,
        resultados_matafuegos=resultados_matafuegos,
        resultados_comprobantes=resultados_comprobantes,
        prioridades=PRIORIDADES,
    )


# --- Routes: Exportar ---

@app.route("/admin/exportar")
@admin_required
def admin_exportar():
    import csv
    import io
    from flask import Response

    tickets = load_tickets()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Sucursal", "Categoria", "Subcategoria", "Descripcion", "Prioridad", "Estado", "Asignado", "Observaciones", "Creado", "Actualizado"])
    for t in tickets:
        writer.writerow([
            t["id"], t["sucursal"], t["categoria"], t["subcategoria"],
            t["descripcion"], t["prioridad"], t["estado"], t["asignado"],
            t["observaciones"], t["creado"][:10], t["actualizado"][:10],
        ])
    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment;filename=tecman_tickets.csv"}
    )


# --- Routes: Seguridad e Higiene ---

SYH_USERS = {
    "patricia": {"password": "syh2026", "nombre": "Patricia"},
}

def syh_login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "syh_user" not in session and "user" not in session:
            return redirect(url_for("syh_login"))
        return f(*args, **kwargs)
    return decorated


@app.route("/syh/login", methods=["GET", "POST"])
def syh_login():
    if request.method == "POST":
        user = request.form.get("usuario", "").lower().strip()
        pwd = request.form.get("password", "")
        if user in SYH_USERS and SYH_USERS[user]["password"] == pwd:
            session["syh_user"] = user
            session["syh_nombre"] = SYH_USERS[user]["nombre"]
            return redirect(url_for("syh_panel"))
        # Also allow admins
        if user in ADMINS and ADMINS[user]["password"] == pwd:
            session["user"] = user
            session["nombre"] = ADMINS[user]["nombre"]
            session["syh_user"] = user
            session["syh_nombre"] = ADMINS[user]["nombre"]
            return redirect(url_for("syh_panel"))
        flash("Usuario o contraseña incorrectos")
    return render_template("syh_login.html")


@app.route("/syh/logout", methods=["GET", "POST"])
def syh_logout():
    session.pop("syh_user", None)
    session.pop("syh_nombre", None)
    return redirect(url_for("syh_login"))


@app.route("/syh")
@syh_login_required
def syh_panel():
    from sucursales_data import SUCURSALES_INFO
    syh_data = load_syh()

    sucursales_syh = []
    for num in sorted(SUCURSALES_INFO.keys()):
        info = SUCURSALES_INFO[num]
        estado = syh_data.get(num, {})
        sucursales_syh.append({
            "num": num,
            "marca": info.get("marca", ""),
            "tienda": info.get("tienda", ""),
            "ciudad": info.get("ciudad", ""),
            "habilitacion": estado.get("habilitacion", "Sin datos"),
            "bomberos": estado.get("bomberos", "Sin datos"),
            "matafuegos": estado.get("matafuegos", "Sin datos"),
            "plano_evacuacion": estado.get("plano_evacuacion", "Sin datos"),
            "senalizacion": estado.get("senalizacion", "Sin datos"),
        })

    tickets_syh = [t for t in load_tickets() if t.get("categoria") == "Seguridad e Higiene"]
    tickets_syh.sort(key=lambda t: t.get("actualizado", t.get("creado", "")), reverse=True)
    tickets_syh = [
        {
            **t,
            "tiene_no_leidas": any(not n.get("leida", True) for n in t.get("notificaciones", [])),
        }
        for t in tickets_syh
    ]
    gestiones_syh = load_syh_gestiones().get("gestiones", [])
    gestiones_syh.sort(key=lambda g: g.get("actualizado", g.get("creado", "")), reverse=True)

    total = len(sucursales_syh)
    habilitadas = sum(1 for s in sucursales_syh if s["habilitacion"] == "Vigente")
    bomberos_ok = sum(1 for s in sucursales_syh if s["bomberos"] == "Aprobado")
    sin_datos = sum(1 for s in sucursales_syh if s["habilitacion"] == "Sin datos")

    return render_template(
        "syh_panel.html",
        sucursales=sucursales_syh,
        total=total,
        habilitadas=habilitadas,
        bomberos_ok=bomberos_ok,
        sin_datos=sin_datos,
        syh_estados=SYH_ESTADOS,
        tickets_syh=tickets_syh,
        tickets_syh_abiertos=sum(1 for t in tickets_syh if t.get("estado") not in ("Resuelto", "Cerrado")),
        tickets_syh_pendientes=sum(1 for t in tickets_syh if t.get("estado") in ("Nuevo", "Abierto", "Pendiente")),
        gestiones_syh=gestiones_syh,
        gestiones_syh_abiertas=sum(1 for g in gestiones_syh if g.get("estado") not in ("Resuelto", "Cerrado")),
    )


@app.route("/syh/matafuegos")
@syh_login_required
def syh_matafuegos():
    from sucursales_data import SUCURSALES_INFO

    items = [_enrich_matafuego(x) for x in load_matafuegos().get("matafuegos", [])]
    filtro_estado = request.args.get("estado", "").strip()
    filtro_suc = request.args.get("sucursal", "").strip()
    por_sucursal = []
    for num in sorted(SUCURSALES_INFO.keys()):
        info = SUCURSALES_INFO[num]
        mats = [m for m in items if m.get("sucursal_num") == num or m.get("sucursal") == f"Sucursal {num}"]
        resumen = _resumen_matafuegos_sucursal(mats)
        if resumen["cantidad"] <= 0:
            continue
        row = {
            "num": num,
            "marca": info.get("marca", ""),
            "ciudad": info.get("ciudad", ""),
            "cantidad": resumen.get("cantidad", 0),
            "tipos": resumen.get("tipos", "-"),
            "proximo_vto": resumen.get("proximo_vto", ""),
            "estado": resumen.get("estado", "Sin datos"),
            "detalle": [m for m in mats[:6]],
        }
        if filtro_estado and row["estado"] != filtro_estado:
            continue
        if filtro_suc and row["num"] != filtro_suc:
            continue
        por_sucursal.append(row)

    stats = _stats_matafuegos(items)
    sin_datos = len(SUCURSALES_INFO) - len({p['num'] for p in por_sucursal})
    por_sucursal.sort(key=lambda x: (0 if x["estado"] == "Vencidos" else 1 if x["estado"] == "Proximo a vencer" else 2, x.get("proximo_vto") or "9999-99-99", x["num"]))
    rechazados_recientes = [x for x in por_sucursal if any(d.get("estado_calc") == "rechazado" for d in x.get("detalle", []))]

    return render_template(
        "syh_matafuegos.html",
        sucursales=por_sucursal,
        stats=stats,
        sin_datos=sin_datos,
        filtro_estado=filtro_estado,
        filtro_suc=filtro_suc,
        rechazados_recientes=rechazados_recientes,
    )


@app.route("/syh/ticket/<int:ticket_id>", methods=["GET", "POST"])
@syh_login_required
def syh_ticket(ticket_id):
    tickets = load_tickets()
    ticket = next((t for t in tickets if t.get("id") == ticket_id and t.get("categoria") == "Seguridad e Higiene"), None)
    if not ticket:
        return "Ticket no encontrado", 404

    if request.method == "POST":
        accion = request.form.get("accion", "").strip()
        ahora = datetime.datetime.now().isoformat()
        autor = session.get("syh_nombre", session.get("nombre", "Patricia"))

        if accion == "responder_suc":
            motivo = request.form.get("motivo", "").strip()
            detalle = request.form.get("motivo_detalle", "").strip()
            labels = {
                "esperando_proveedor": "Esperando proveedor",
                "esperando_materiales": "Esperando materiales",
                "otra": "Otra",
            }
            label = labels.get(motivo, motivo or "Respuesta")
            mensaje = label if motivo != "otra" else (detalle or label)
            if detalle and motivo != "otra":
                mensaje += f" - {detalle}"
            ticket.setdefault("notas", []).append({
                "autor": autor,
                "fecha": ahora,
                "texto": f"Respuesta a sucursal: {mensaje}",
            })
            ticket.setdefault("notificaciones", []).append({
                "fecha": ahora,
                "texto": mensaje,
                "leida": False,
            })
            ticket["estado_respuesta"] = label
            if ticket.get("estado") in ("Nuevo", "Abierto"):
                ticket["estado"] = "Pendiente"
            ticket["actualizado"] = ahora
            save_tickets(tickets)
            flash("Respuesta enviada a la sucursal")
            return redirect(url_for("syh_ticket", ticket_id=ticket_id))

        if accion == "agregar_nota_syh":
            nueva_nota = request.form.get("nueva_nota", "").strip()
            if nueva_nota:
                ticket.setdefault("notas", []).append({
                    "autor": autor,
                    "fecha": ahora,
                    "texto": nueva_nota,
                })
                ticket["actualizado"] = ahora
                save_tickets(tickets)
                flash("Nota agregada")
            return redirect(url_for("syh_ticket", ticket_id=ticket_id))

        if accion == "actualizar_ticket_syh":
            ticket["estado"] = request.form.get("estado", ticket.get("estado", "Nuevo"))
            ticket["observaciones"] = request.form.get("observaciones", ticket.get("observaciones", ""))
            ticket.setdefault("notas", []).append({
                "autor": autor,
                "fecha": ahora,
                "texto": f"Actualización S&H: estado {ticket['estado']}",
            })
            ticket["actualizado"] = ahora
            save_tickets(tickets)
            flash("Ticket actualizado")
            return redirect(url_for("syh_ticket", ticket_id=ticket_id))

    return render_template(
        "syh_ticket.html",
        ticket=ticket,
        estados=ESTADOS,
    )


@app.route("/syh/gestion/nueva", methods=["GET", "POST"])
@syh_login_required
def syh_gestion_nueva():
    if request.method == "POST":
        sucursal = request.form.get("sucursal", "").strip()
        if not sucursal:
            flash("Seleccione una sucursal")
            return redirect(url_for("syh_gestion_nueva"))
        suc_num = sucursal.replace("Sucursal ", "").strip()
        data = load_syh_gestiones()
        items = data.setdefault("gestiones", [])
        ahora = datetime.datetime.now().isoformat()
        gid = max([g.get("id", 0) for g in items] + [0]) + 1
        nueva = {
            "id": gid,
            "sucursal": sucursal,
            "sucursal_num": suc_num,
            "tipo": request.form.get("tipo", "").strip(),
            "origen": request.form.get("origen", "").strip(),
            "estado": request.form.get("estado", "Pendiente").strip() or "Pendiente",
            "fecha_objetivo": request.form.get("fecha_objetivo", "").strip(),
            "detalle": request.form.get("detalle", "").strip(),
            "observaciones": request.form.get("observaciones", "").strip(),
            "creado": ahora,
            "actualizado": ahora,
            "creado_por": session.get("syh_nombre", session.get("nombre", "Patricia")),
            "historial": [{
                "autor": session.get("syh_nombre", session.get("nombre", "Patricia")),
                "fecha": ahora,
                "texto": "Gestión S&H creada",
            }],
        }
        items.append(nueva)
        save_syh_gestiones(data)
        flash("Gestión S&H creada")
        return redirect(url_for("syh_panel") + "#gestiones-syh")

    return render_template("syh_gestion_form.html", sucursales=SUCURSALES)


@app.route("/syh/sucursal/<suc_num>", methods=["GET", "POST"])
@syh_login_required
def syh_edit(suc_num):
    from sucursales_data import SUCURSALES_INFO
    info = SUCURSALES_INFO.get(suc_num, {})
    syh_data = load_syh()
    estado = syh_data.get(suc_num, {})

    if request.method == "POST":
        syh_data[suc_num] = {
            "habilitacion": request.form.get("habilitacion", ""),
            "habilitacion_vencimiento": request.form.get("habilitacion_vencimiento", "").strip(),
            "bomberos": request.form.get("bomberos", ""),
            "matafuegos": request.form.get("matafuegos", ""),
            "matafuegos_cantidad": request.form.get("matafuegos_cantidad", ""),
            "matafuegos_vencimiento": request.form.get("matafuegos_vencimiento", ""),
            "plano_evacuacion": request.form.get("plano_evacuacion", ""),
            "senalizacion": request.form.get("senalizacion", ""),
            "observaciones": request.form.get("observaciones", ""),
            "actualizado_por": session.get("syh_nombre", session.get("nombre", "")),
            "actualizado": datetime.datetime.now().isoformat(),
        }
        f = request.files.get("documento")
        if f and f.filename:
            ext = Path(f.filename).suffix.lower()
            if ext in (".pdf", ".jpg", ".jpeg", ".png", ".gif", ".webp"):
                fname = f"syh_{suc_num}_{uuid.uuid4().hex[:8]}{ext}"
                f.save(str(UPLOADS_DIR / fname))
                if "documentos" not in syh_data[suc_num]:
                    syh_data[suc_num]["documentos"] = []
                syh_data[suc_num]["documentos"] = estado.get("documentos", []) + [{"nombre": f.filename, "archivo": fname, "fecha": datetime.datetime.now().isoformat()}]
            else:
                syh_data[suc_num]["documentos"] = estado.get("documentos", [])
        else:
            syh_data[suc_num]["documentos"] = estado.get("documentos", [])
        syh_data[suc_num]["documentos_detallados"] = _build_syh_documentos_detallados(request.form, request.files, suc_num, estado)
        save_syh(syh_data)
        flash("Sucursal actualizada")
        return redirect(url_for("syh_panel"))

    return render_template(
        "syh_edit.html",
        suc_num=suc_num,
        info=info,
        estado=estado,
        syh_estados=SYH_ESTADOS,
        syh_documentos_categorias=SYH_DOCUMENTOS_CATEGORIAS,
        syh_capacitaciones_subtipos=SYH_CAPACITACIONES_SUBTIPOS,
    )


# --- Routes: S&H Admin (duplicate for admin access) ---

@app.route("/admin/syh")
@admin_required
def admin_syh():
    from sucursales_data import SUCURSALES_INFO
    syh_data = load_syh()
    alertas_syh = sync_alertas_syh()

    # Mapa sucursal_num → habilitacion detallada (fuente de verdad si existe)
    habs_detalle = {}
    for h in load_habilitaciones().get("habilitaciones", []):
        sn = str(h.get("sucursal_num") or "").strip().lstrip("0") or str(h.get("sucursal", "")).replace("Sucursal ", "").strip().lstrip("0")
        if sn:
            he = _enrich_habilitacion(h)
            ESTADO_MAP = {"vigente": "Vigente", "por_vencer": "Por vencer", "vencida": "Vencida", "sin_dato": "Sin datos"}
            habs_detalle[sn] = ESTADO_MAP.get(he.get("estado", ""), "Sin datos")

    sucursales_syh = []
    for num in sorted(SUCURSALES_INFO.keys()):
        info = SUCURSALES_INFO[num]
        estado = syh_data.get(num, {})
        num_strip = num.lstrip("0")
        hab_status = habs_detalle.get(num_strip) or habs_detalle.get(num) or estado.get("habilitacion", "Sin datos")
        sucursales_syh.append({
            "num": num,
            "marca": info.get("marca", ""),
            "tienda": info.get("tienda", ""),
            "ciudad": info.get("ciudad", ""),
            "habilitacion": hab_status,
            "habilitacion_desde_modulo": num_strip in habs_detalle or num in habs_detalle,
            "bomberos": estado.get("bomberos", "Sin datos"),
            "matafuegos": estado.get("matafuegos", "Sin datos"),
            "red_incendio": estado.get("red_incendio", "Sin datos"),
            "plano_evacuacion": estado.get("plano_evacuacion", "Sin datos"),
            "senalizacion": estado.get("senalizacion", "Sin datos"),
        })

    # Stats
    total = len(sucursales_syh)
    habilitadas = sum(1 for s in sucursales_syh if s["habilitacion"] == "Vigente")
    bomberos_ok = sum(1 for s in sucursales_syh if s["bomberos"] == "Aprobado")
    sin_datos = sum(1 for s in sucursales_syh if s["habilitacion"] == "Sin datos")

    matafuegos_data = load_matafuegos().get("matafuegos", [])
    rechazados_recientes = []
    for s in sucursales_syh:
        mats = [m for m in matafuegos_data if m.get("sucursal_num") == s["num"] or m.get("sucursal") == f"Sucursal {s['num']}"]
        resumen = _resumen_matafuegos_sucursal(mats)
        s["matafuegos_detalle"] = resumen["cantidad"]
        s["matafuegos"] = resumen["estado"]
        s["matafuegos_tipos"] = resumen["tipos"]
        s["matafuegos_proximo_vto"] = resumen["proximo_vto"]
        s["matafuegos_rechazados"] = resumen.get("rechazados", 0)
        if resumen.get("rechazados", 0):
            rechazados_recientes.append({
                "num": s["num"],
                "marca": s["marca"],
                "ciudad": s["ciudad"],
                "rechazados": resumen.get("rechazados", 0),
                "tipos": resumen.get("tipos", "-"),
            })

    tickets_syh = [t for t in load_tickets() if t.get("categoria") == "Seguridad e Higiene"]
    tickets_syh.sort(key=lambda t: t.get("actualizado", t.get("creado", "")), reverse=True)
    gestiones_syh = load_syh_gestiones().get("gestiones", [])
    gestiones_syh.sort(key=lambda g: g.get("actualizado", g.get("creado", "")), reverse=True)

    return render_template(
        "admin_syh.html",
        sucursales=sucursales_syh,
        total=total,
        habilitadas=habilitadas,
        bomberos_ok=bomberos_ok,
        sin_datos=sin_datos,
        syh_estados=SYH_ESTADOS,
        matafuegos_stats=_stats_matafuegos(matafuegos_data),
        alertas_syh=alertas_syh,
        rechazados_recientes=rechazados_recientes,
        tickets_syh=tickets_syh,
        tickets_syh_abiertos=sum(1 for t in tickets_syh if t.get("estado") not in ("Resuelto", "Cerrado")),
        gestiones_syh=gestiones_syh,
        gestiones_syh_abiertas=sum(1 for g in gestiones_syh if g.get("estado") not in ("Resuelto", "Cerrado")),
    )


@app.route("/admin/syh/matafuegos", methods=["GET", "POST"])
@admin_required
def admin_syh_matafuegos():
    data = load_matafuegos()
    items = [_enrich_matafuego(x) for x in data.get("matafuegos", [])]

    if request.method == "POST":
        sucursal = request.form.get("sucursal", "").strip()
        if not sucursal:
            flash("Seleccione una sucursal")
            return redirect(url_for("admin_syh_matafuegos"))
        suc_num = sucursal.replace("Sucursal ", "").strip()
        nuevo = {
            "id": uuid.uuid4().hex[:12],
            "sucursal": sucursal,
            "sucursal_num": suc_num,
            "tipo": request.form.get("tipo", "").strip(),
            "cantidad": _parse_int_or_none(request.form.get("cantidad", "")) or 1,
            "ubicacion": request.form.get("ubicacion", "").strip(),
            "fecha_carga": request.form.get("fecha_carga", "").strip(),
            "fecha_vencimiento": request.form.get("fecha_vencimiento", "").strip(),
            "estado_manual": request.form.get("estado_manual", "").strip(),
            "observaciones": request.form.get("observaciones", "").strip(),
            "created_at": datetime.datetime.now().isoformat(),
            "cargado_por": session.get("nombre", ""),
        }
        data.setdefault("matafuegos", []).append(nuevo)
        save_matafuegos(data)
        flash("Matafuego cargado")
        return redirect(url_for("admin_syh_matafuegos"))

    filtro_sucursal = request.args.get("sucursal", "").strip()
    if filtro_sucursal:
        items = [m for m in items if m.get("sucursal") == filtro_sucursal]
    items.sort(key=lambda m: (m.get("estado_calc") not in ("rechazado", "vencido"), m.get("fecha_vencimiento", "9999-99-99") or "9999-99-99", m.get("sucursal", "")))
    return render_template(
        "admin_matafuegos.html",
        matafuegos=items,
        stats=_stats_matafuegos(data.get("matafuegos", [])),
        sucursales=SUCURSALES,
        filtro_sucursal=filtro_sucursal,
    )


@app.route("/admin/syh/matafuegos/<mid>/eliminar", methods=["POST"])
@admin_required
def admin_syh_matafuegos_eliminar(mid):
    data = load_matafuegos()
    antes = len(data.get("matafuegos", []))
    data["matafuegos"] = [x for x in data.get("matafuegos", []) if x.get("id") != mid]
    if len(data["matafuegos"]) < antes:
        save_matafuegos(data)
        flash("Matafuego eliminado")
    return redirect(url_for("admin_syh_matafuegos"))


@app.route("/suc/syh/asistencia", methods=["POST"])
@suc_login_required
def suc_syh_asistencia():
    tickets = load_tickets()
    new_id = next_ticket_id(tickets)
    motivo = request.form.get("motivo", "").strip() or "Asistencia S&H"
    comentario = request.form.get("comentario", "").strip()
    now_iso = datetime.datetime.now().isoformat()
    nuevo = {
        "id": new_id,
        "tipo": "syh_asistencia",
        "sucursal": session.get("suc_nombre", ""),
        "descripcion": comentario or motivo,
        "estado": "Nuevo",
        "asignado": "Patricia",
        "prioridad": 2,
        "creado": now_iso,
        "actualizado": now_iso,
        "categoria": "Seguridad e Higiene",
        "subcategoria": motivo,
        "fotos": [],
        "notas": [{"autor": session.get("suc_nombre", "Sucursal"), "fecha": now_iso, "texto": f"Solicitud de asistencia S&H: {motivo}" + (f" - {comentario}" if comentario else "")}],
    }
    tickets.append(nuevo)
    save_tickets(tickets)
    agregar_notif_admin(
        titulo=f"🧯 Asistencia S&H solicitada #{new_id}",
        detalle=f"{session.get('suc_nombre', 'Sucursal')} solicitó asistencia. Motivo: {motivo}" + (f"\nDetalle: {comentario}" if comentario else ""),
        tipo="syh",
        autor=session.get("suc_nombre", "Sucursal"),
        link=url_for("admin_ticket", ticket_id=new_id),
    )
    flash("Solicitud de asistencia enviada")
    return redirect(url_for("suc_panel"))


@app.route("/admin/syh/<suc_num>", methods=["GET", "POST"])
@admin_required
def admin_syh_edit(suc_num):
    from sucursales_data import SUCURSALES_INFO
    info = SUCURSALES_INFO.get(suc_num, {})
    syh_data = load_syh()
    estado = syh_data.get(suc_num, {})

    if request.method == "POST":
        syh_data[suc_num] = {
            "habilitacion": request.form.get("habilitacion", ""),
            "habilitacion_vencimiento": request.form.get("habilitacion_vencimiento", "").strip(),
            "bomberos": request.form.get("bomberos", ""),
            "matafuegos": request.form.get("matafuegos", ""),
            "matafuegos_cantidad": request.form.get("matafuegos_cantidad", ""),
            "matafuegos_vencimiento": request.form.get("matafuegos_vencimiento", ""),
            "red_incendio": request.form.get("red_incendio", ""),
            "plano_evacuacion": request.form.get("plano_evacuacion", ""),
            "senalizacion": request.form.get("senalizacion", ""),
            "observaciones": request.form.get("observaciones", ""),
            "actualizado_por": session.get("nombre", ""),
            "actualizado": datetime.datetime.now().isoformat(),
        }

        # Handle document upload
        f = request.files.get("documento")
        if f and f.filename:
            ext = Path(f.filename).suffix.lower()
            if ext in (".pdf", ".jpg", ".jpeg", ".png", ".gif", ".webp"):
                fname = f"syh_{suc_num}_{uuid.uuid4().hex[:8]}{ext}"
                f.save(str(UPLOADS_DIR / fname))
                if "documentos" not in syh_data[suc_num]:
                    syh_data[suc_num]["documentos"] = []
                syh_data[suc_num]["documentos"] = estado.get("documentos", []) + [{"nombre": f.filename, "archivo": fname, "fecha": datetime.datetime.now().isoformat()}]
            else:
                syh_data[suc_num]["documentos"] = estado.get("documentos", [])
        else:
            syh_data[suc_num]["documentos"] = estado.get("documentos", [])

        syh_data[suc_num]["documentos_detallados"] = _build_syh_documentos_detallados(request.form, request.files, suc_num, estado)
        save_syh(syh_data)
        flash("Sucursal actualizada")
        return redirect(url_for("admin_syh"))

    return render_template(
        "admin_syh_edit.html",
        suc_num=suc_num,
        info=info,
        estado=estado,
        syh_estados=SYH_ESTADOS,
        syh_documentos_categorias=SYH_DOCUMENTOS_CATEGORIAS,
        syh_capacitaciones_subtipos=SYH_CAPACITACIONES_SUBTIPOS,
    )


# --- Routes: Jonathan - Pedidos de materiales ---

@app.route("/admin/pedidos")
@login_required
def admin_pedidos():
    tickets = load_tickets()
    # Filter material tickets assigned to Jonathan
    pedidos = [t for t in tickets if (t.get("categoria") in ("Materiales", "Solicitud de materiales") or t.get("tipo") == "materiales") and t["estado"] not in ("Cerrado",)]
    pendientes = [t for t in pedidos if t["estado"] in ("Nuevo", "Abierto")]
    en_proceso = [t for t in pedidos if t["estado"] in ("En progreso", "Materiales recibidos", "Pendiente")]
    resueltos = [t for t in pedidos if t["estado"] == "Resuelto"]

    return render_template(
        "admin_pedidos.html",
        pendientes=pendientes,
        en_proceso=en_proceso,
        resueltos=resueltos,
        prioridades=PRIORIDADES,
    )


@app.route("/admin/pedido/<int:ticket_id>", methods=["GET", "POST"])
@login_required
def admin_pedido(ticket_id):
    tickets = load_tickets()
    ticket = next((t for t in tickets if t["id"] == ticket_id), None)
    if not ticket:
        return "Ticket no encontrado", 404

    stock = load_stock()
    central = stock.get("central", {})
    central_qtys = {k: v.get("cantidad", 0) for k, v in central.items()}

    # Check if sucursal is AMBA
    suc_num = ticket["sucursal"].replace("Sucursal ", "").strip()
    es_amba = suc_num not in SUCS_CORDOBA and suc_num not in SUCS_NOA and suc_num not in SUCS_MENDOZA and suc_num not in SUCS_SANJUAN
    proveedores_sucursal = get_proveedores_para_sucursal(suc_num)
    es_ceyh = es_sucursal_ceyh(suc_num)

    # Stock relevante al pedido
    cat = ticket.get("categoria_mat", "").lower()
    subitem = ticket.get("subitem_mat", "").lower()
    stock_relevante = {}
    stock_similares = {}
    for k, qty in central_qtys.items():
        k_lower = k.lower()
        if cat and (cat in k_lower or k_lower in cat):
            stock_relevante[k] = qty
        elif subitem and (subitem in k_lower or k_lower in subitem):
            stock_relevante[k] = qty
        else:
            first_word = cat.split()[0] if cat else ""
            if first_word and len(first_word) > 3 and first_word in k_lower:
                stock_similares[k] = qty

    ticket.setdefault("materiales_agregados", [])
    ticket.setdefault("materiales_a_comprar", [])

    if request.method == "POST":
        accion = request.form.get("accion", "")

        if "notas" not in ticket:
            ticket["notas"] = []

        if accion == "subir_guia":
            archivo = request.files.get("guia_archivo")
            numero = request.form.get("guia_numero", "").strip()
            if archivo and archivo.filename:
                ext = archivo.filename.rsplit(".", 1)[-1].lower()
                fname = f"guia_{ticket_id}_{uuid.uuid4().hex[:8]}.{ext}"
                archivo.save(str(GUIAS_DIR / fname))
                ticket["guia_transporte"] = fname
                ticket["guia_transporte_numero"] = numero
                ticket["notas"].append({
                    "autor": session.get("nombre", "Admin"),
                    "fecha": datetime.datetime.now().isoformat(),
                    "texto": f"Guía de transporte cargada: {numero or fname}",
                })
            ticket["actualizado"] = datetime.datetime.now().isoformat()
            save_tickets(tickets)
            flash("Guía cargada correctamente")
            return redirect(url_for("admin_pedido", ticket_id=ticket_id))

        elif accion == "quitar_guia":
            ticket.pop("guia_transporte", None)
            ticket.pop("guia_transporte_numero", None)
            ticket["actualizado"] = datetime.datetime.now().isoformat()
            save_tickets(tickets)
            flash("Guía eliminada")
            return redirect(url_for("admin_pedido", ticket_id=ticket_id))

        if accion == "gestion_retiro":
            retiro_tipo = request.form.get("retiro_tipo", "envio")
            ticket["retiro_tipo"] = retiro_tipo
            fecha_envio = request.form.get("fecha_envio", "").strip()
            if fecha_envio:
                ticket["fecha_envio"] = fecha_envio
            if retiro_tipo == "proveedor":
                prov = request.form.get("proveedor_nombre", "").strip()
                if prov == "__otro__":
                    prov = request.form.get("proveedor_otro_nombre", "").strip()
                ticket["proveedor_nombre"] = prov
                ticket["proveedor_detalle"] = request.form.get("proveedor_detalle", "").strip()
                ticket["retiro_proveedor"] = True
                nota_txt = f"Retiro definido: PROVEEDOR - {prov}"
                if ticket["proveedor_detalle"]:
                    nota_txt += f" ({ticket['proveedor_detalle']})"
            elif retiro_tipo == "personal_propio":
                ticket["retiro_proveedor"] = False
                ticket["proveedor_nombre"] = ""
                ticket["proveedor_detalle"] = ""
                nota_txt = "Retiro definido: PERSONAL PROPIO"
            else:
                ticket["retiro_proveedor"] = False
                ticket["proveedor_nombre"] = ""
                ticket["proveedor_detalle"] = ""
                nota_txt = "Retiro definido: ENVIO a sucursal"
            if fecha_envio:
                nota_txt += f" | Fecha programada: {fecha_envio}"
            ticket["notas"].append({
                "autor": session.get("nombre", "Admin"),
                "fecha": datetime.datetime.now().isoformat(),
                "texto": nota_txt,
            })
            ticket["actualizado"] = datetime.datetime.now().isoformat()
            save_tickets(tickets)
            flash("Retiro actualizado")
            return redirect(url_for("admin_pedido", ticket_id=ticket_id))

        if accion == "cuento_material":
            metodo_envio = request.form.get("metodo_envio", "")
            ticket["estado"] = "En progreso"
            ticket["metodo_envio"] = metodo_envio
            ticket["notas"].append({
                "autor": session.get("nombre", "Jonatan"),
                "fecha": datetime.datetime.now().isoformat(),
                "texto": f"Cuento con material. Envio: {metodo_envio}",
            })

        elif accion == "solicitar_compras":
            detalle = request.form.get("detalle_compras", "")
            ticket["estado"] = "Pendiente"
            ticket["detalle_compras"] = detalle  # internal only
            ticket["notas"].append({
                "autor": session.get("nombre", "Jonatan"),
                "fecha": datetime.datetime.now().isoformat(),
                "texto": "Pedido realizado a compras",
            })

        elif accion == "agregar_material_stock":
            item = request.form.get("item_stock", "").strip()
            cantidad = _parse_int_or_none(request.form.get("cantidad_stock", "")) or 1
            detalle_extra = request.form.get("detalle_stock", "").strip()
            disponible = get_central_qty(load_stock(), item) if item else 0
            if not item:
                flash("Seleccioná un material de stock")
                return redirect(url_for("admin_pedido", ticket_id=ticket_id))
            if cantidad <= 0:
                flash("La cantidad debe ser mayor a 0")
                return redirect(url_for("admin_pedido", ticket_id=ticket_id))
            if disponible < cantidad:
                flash(f"Stock insuficiente para {item}. Disponible: {disponible}")
                return redirect(url_for("admin_pedido", ticket_id=ticket_id))
            ticket["materiales_agregados"].append({
                "id": uuid.uuid4().hex[:10],
                "item": item,
                "cantidad": cantidad,
                "detalle": detalle_extra,
                "agregado_por": session.get("nombre", "Jonatan"),
                "fecha": datetime.datetime.now().isoformat(),
            })
            ticket["notas"].append({
                "autor": session.get("nombre", "Jonatan"),
                "fecha": datetime.datetime.now().isoformat(),
                "texto": f"Agregó material complementario desde stock: {item} x{cantidad}" + (f" ({detalle_extra})" if detalle_extra else ""),
            })
            ticket["estado"] = "En progreso"
            ticket["actualizado"] = datetime.datetime.now().isoformat()
            save_tickets(tickets)
            flash("Material agregado al ticket")
            return redirect(url_for("admin_pedido", ticket_id=ticket_id))

        elif accion == "derivar_a_compras":
            item = request.form.get("item_compra", "").strip()
            cantidad = _parse_int_or_none(request.form.get("cantidad_compra", "")) or 1
            requisicion = request.form.get("requisicion", "").strip()
            detalle = request.form.get("detalle_compra_item", "").strip()
            if not item:
                flash("Indicá el material a comprar")
                return redirect(url_for("admin_pedido", ticket_id=ticket_id))
            if not requisicion:
                flash("Indicá el número de requisición")
                return redirect(url_for("admin_pedido", ticket_id=ticket_id))
            ticket["materiales_a_comprar"].append({
                "id": uuid.uuid4().hex[:10],
                "item": item,
                "cantidad": cantidad,
                "requisicion": requisicion,
                "detalle": detalle,
                "pedido_por": session.get("nombre", "Jonatan"),
                "estado": "Pendiente compras",
                "fecha": datetime.datetime.now().isoformat(),
            })
            ticket["estado"] = "Pendiente"
            ticket["notas"].append({
                "autor": session.get("nombre", "Jonatan"),
                "fecha": datetime.datetime.now().isoformat(),
                "texto": f"Derivó a Compras: {item} x{cantidad} | Requisición: {requisicion}" + (f" ({detalle})" if detalle else ""),
            })
            ticket["actualizado"] = datetime.datetime.now().isoformat()
            save_tickets(tickets)
            flash("Pedido derivado a Compras")
            return redirect(url_for("admin_pedido", ticket_id=ticket_id))

        elif accion == "enviado":
            ticket["estado"] = "Resuelto"
            metodo = ticket.get("metodo_envio", "")
            # Descontar del stock central e imputar costo a la sucursal
            cat = ticket.get("categoria_mat", "")
            subitem = ticket.get("subitem_mat", "")
            try:
                cantidad_env = int(ticket.get("cantidad_mat", 1))
            except (ValueError, TypeError):
                cantidad_env = 1
            item_key = f"{cat} > {subitem}" if subitem else cat
            descuento_txt = ""
            imputacion_txt = ""
            if item_key:
                stock_data = load_stock()
                disponible = get_central_qty(stock_data, item_key)
                nuevo = max(0, disponible - cantidad_env)
                if nuevo == 0 and item_key in stock_data.get("central", {}):
                    # Preservar precio en item con cantidad 0
                    stock_data["central"][item_key]["cantidad"] = 0
                elif item_key in stock_data.get("central", {}):
                    stock_data["central"][item_key]["cantidad"] = nuevo
                save_stock(stock_data)

                # FIFO real: consumir lotes para imputar el costo contra la
                # factura/remito de origen. Fallback al precio historico si el
                # item todavia no tiene lotes (datos viejos de prueba).
                fifo = consumir_lotes_fifo(item_key, cantidad_env)
                sin_trazabilidad = False
                lotes_breakdown = fifo["breakdown"]

                if fifo["consumido"] >= cantidad_env and fifo["consumido"] > 0:
                    precio_unit = fifo["precio_promedio"]
                    imputacion_monto = fifo["monto_total"]
                else:
                    # No alcanzan los lotes: usar fallback para lo faltante
                    faltante = cantidad_env - fifo["consumido"]
                    precio_fallback = _get_precio_historico(item_key) or get_central_precio(stock_data, item_key) or 0.0
                    monto_fallback = round(faltante * precio_fallback, 2)
                    total_monto = round(fifo["monto_total"] + monto_fallback, 2)
                    imputacion_monto = total_monto
                    precio_unit = round(total_monto / cantidad_env, 4) if cantidad_env > 0 else precio_fallback
                    if faltante > 0:
                        sin_trazabilidad = True

                ticket["imputacion_item"] = item_key
                ticket["imputacion_cantidad"] = cantidad_env
                ticket["imputacion_precio_unitario"] = precio_unit
                ticket["imputacion_monto"] = imputacion_monto
                ticket["imputacion_fecha"] = datetime.datetime.now().isoformat()
                ticket["imputacion_lotes"] = lotes_breakdown
                if sin_trazabilidad:
                    ticket["imputacion_sin_trazabilidad_fifo"] = True

                descuento_txt = f" | Stock descontado: '{item_key}' -{cantidad_env} (quedaron {nuevo})"
                if precio_unit > 0:
                    imputacion_txt = f" | Imputado a {ticket.get('sucursal', '')}: ${imputacion_monto:,.2f} ({cantidad_env} x ${precio_unit:,.2f})"
                else:
                    imputacion_txt = " | Sin precio unitario cargado (imputacion $0)"

                nota_mov = f"Enviado por ticket #{ticket.get('id')}"
                if metodo:
                    nota_mov += f" ({metodo})"

                # Resumen de trazabilidad al movimiento
                if lotes_breakdown:
                    if len(lotes_breakdown) == 1:
                        numero_origen = lotes_breakdown[0].get("numero_comprobante", "") or None
                        proveedor_origen = lotes_breakdown[0].get("proveedor", "") or None
                    else:
                        nums = [l.get("numero_comprobante", "") for l in lotes_breakdown if l.get("numero_comprobante")]
                        provs = [l.get("proveedor", "") for l in lotes_breakdown if l.get("proveedor")]
                        numero_origen = ", ".join(dict.fromkeys(nums)) or None
                        proveedor_origen = ", ".join(dict.fromkeys(provs)) or None
                else:
                    numero_origen = None
                    proveedor_origen = None

                registrar_movimiento(
                    item=item_key,
                    tipo="egreso",
                    cantidad=cantidad_env,
                    sucursal=ticket.get("sucursal", ""),
                    ticket_id=ticket.get("id"),
                    nota=nota_mov,
                    monto_imputado=imputacion_monto,
                    precio_unitario=precio_unit,
                    lotes_origen=lotes_breakdown or None,
                    numero_comprobante_origen=numero_origen,
                    proveedor_origen=proveedor_origen,
                    sin_trazabilidad_fifo=sin_trazabilidad or None,
                )
            ticket["notas"].append({
                "autor": session.get("nombre", "Jonatan"),
                "fecha": datetime.datetime.now().isoformat(),
                "texto": f"Material enviado a sucursal ({metodo}){descuento_txt}{imputacion_txt}",
            })
            # Notify sucursal
            if "notificaciones" not in ticket:
                ticket["notificaciones"] = []
            ticket["notificaciones"].append({
                "fecha": datetime.datetime.now().isoformat(),
                "texto": f"Materiales enviados desde Central ({metodo}). Por favor confirme recepcion adjuntando el remito.",
                "leida": False,
            })

        ticket["actualizado"] = datetime.datetime.now().isoformat()
        save_tickets(tickets)
        flash("Pedido actualizado")
        return redirect(url_for("admin_pedido", ticket_id=ticket_id))

    trabajo_prov_ticket = None
    if ticket.get("trabajo_proveedor_ticket_id"):
        trabajo_prov_ticket = next(
            (x for x in tickets if x["id"] == ticket["trabajo_proveedor_ticket_id"]),
            None,
        )

    return render_template(
        "admin_pedido.html",
        ticket=ticket,
        central=central,
        central_qtys=central_qtys,
        es_amba=es_amba,
        prioridades=PRIORIDADES,
        proveedores_sucursal=proveedores_sucursal,
        trabajo_prov_ticket=trabajo_prov_ticket,
        stock_relevante=stock_relevante,
        stock_similares=stock_similares,
        es_ceyh=es_ceyh,
    )


@app.route("/admin/pedido/<int:ticket_id>/guia")
@login_required
def admin_pedido_guia(ticket_id):
    """Genera una Guia Interna de Transporte para el pedido, lista para imprimir."""
    from sucursales_data import SUCURSALES_INFO

    tickets = load_tickets()
    ticket = next((t for t in tickets if t["id"] == ticket_id), None)
    if not ticket:
        return "Ticket no encontrado", 404

    # Numero de guia: si el ticket ya tiene uno, lo reutilizamos.
    existing = ticket.get("guia_transporte_numero")
    if existing:
        existing_str = str(existing).strip()
        if "-" in existing_str:
            guia_num_fmt = existing_str
        else:
            guia_num_fmt = _formatear_guia_numero(existing_str)
    else:
        n = _next_guia_numero()
        guia_num_fmt = _formatear_guia_numero(n)
        ticket["guia_transporte_numero"] = guia_num_fmt
        ticket["actualizado"] = datetime.datetime.now().isoformat()
        save_tickets(tickets)

    # Datos de la sucursal destino.
    suc_raw = ticket.get("sucursal", "") or ""
    suc_num = suc_raw.replace("Sucursal ", "").strip()
    info = SUCURSALES_INFO.get(suc_num, {})
    partes_dir = []
    if info.get("direccion"):
        partes_dir.append(info["direccion"])
    if info.get("ciudad"):
        partes_dir.append(info["ciudad"])
    if info.get("provincia"):
        partes_dir.append(info["provincia"])
    sucursal_direccion = ", ".join(partes_dir)

    # Quien retira: CEYH si la sucursal lo tiene; sino el proveedor cargado.
    if es_sucursal_ceyh(suc_num):
        retira = "RETIRA CEYH"
    elif ticket.get("retiro_tipo") == "proveedor" and ticket.get("proveedor_nombre"):
        retira = ticket.get("proveedor_nombre", "")
    else:
        retira = ""

    # Items del pedido vivo: original + agregados desde mantenimiento.
    items = []

    cat = ticket.get("categoria_mat", "") or ""
    subitem = ticket.get("subitem_mat", "") or ""
    try:
        cantidad = int(ticket.get("cantidad_mat") or 1)
    except (TypeError, ValueError):
        cantidad = 1
    detalle = f"{cat} - {subitem}" if (cat and subitem) else (cat or subitem or ticket.get("subcategoria", ""))
    if detalle:
        items.append({"cantidad": cantidad, "detalle": detalle})

    for agregado in ticket.get("materiales_agregados", []) or []:
        item_agregado = (agregado.get("item") or "").strip()
        if not item_agregado:
            continue
        try:
            cantidad_agregada = int(agregado.get("cantidad") or 1)
        except (TypeError, ValueError):
            cantidad_agregada = 1
        detalle_agregado = item_agregado
        if agregado.get("detalle"):
            detalle_agregado += f" — {agregado.get('detalle')}"
        items.append({"cantidad": cantidad_agregada, "detalle": detalle_agregado})

    return render_template(
        "guia_transporte.html",
        ticket=ticket,
        guia_numero=guia_num_fmt,
        fecha_hoy=datetime.date.today().strftime("%d/%m/%Y"),
        sucursal_nombre=suc_raw,
        sucursal_direccion=sucursal_direccion,
        retira=retira,
        items=items,
    )


# --- Routes: Stock / Inventario deposito ---

@app.route("/admin/stock")
@login_required
def admin_stock():
    from categories_data import MATERIAL_CATEGORIAS

    stock = load_stock()
    transfers = load_transfers()
    central = stock.get("central", {})
    sucursales_stock = stock.get("sucursales", {})

    # Sort items → lista de (item, cantidad, precio_unitario)
    central_items = sorted(
        ((k, v.get("cantidad", 0), v.get("precio_unitario", 0.0)) for k, v in central.items()),
        key=lambda x: x[0],
    )
    total_items_central = sum(c for _, c, _ in central_items)
    valor_stock_central = sum(c * p for _, c, p in central_items)

    # Recent transfers
    recent = sorted(transfers, key=lambda x: x.get("fecha", ""), reverse=True)[:20]

    return render_template(
        "admin_stock.html",
        central=central_items,
        total_items=total_items_central,
        valor_stock_central=valor_stock_central,
        sucursales_stock=sucursales_stock,
        transfers=recent,
        sucursales=SUCURSALES,
        material_categorias=MATERIAL_CATEGORIAS,
    )


@app.route("/admin/stock/add", methods=["POST"])
@admin_required
def stock_add():
    stock = load_stock()
    # El item puede venir armado desde categoria + subitem o como texto libre.
    categoria = request.form.get("categoria_mat", "").strip()
    subitem = request.form.get("subitem", "").strip()
    item_libre = request.form.get("item", "").strip()

    if categoria and subitem:
        item = f"{categoria} > {subitem}"
    elif categoria:
        item = categoria
    else:
        item = item_libre

    cantidad = int(request.form.get("cantidad", 0))
    ubicacion = request.form.get("ubicacion", "central")

    if item and cantidad > 0:
        if ubicacion == "central":
            actual = get_central_qty(stock, item)
            set_central_qty(stock, item, actual + cantidad)
            destino_label = "Central Dabra"
        else:
            if ubicacion not in stock["sucursales"]:
                stock["sucursales"][ubicacion] = {}
            stock["sucursales"][ubicacion][item] = stock["sucursales"][ubicacion].get(item, 0) + cantidad
            destino_label = ubicacion
        save_stock(stock)
        registrar_movimiento(
            item=item,
            tipo="ingreso",
            cantidad=cantidad,
            sucursal=destino_label,
            nota=f"Ingreso manual a {destino_label} por {session.get('nombre', 'admin')}",
        )
        flash(f"Agregado: {cantidad}x {item} en {ubicacion}")
    return redirect(url_for("admin_stock"))


@app.route("/admin/stock/transfer", methods=["POST"])
@login_required
def stock_transfer():
    stock = load_stock()
    transfers = load_transfers()

    item = request.form.get("item", "").strip()
    cantidad = int(request.form.get("cantidad", 0))
    destino = request.form.get("destino", "")

    if item and cantidad > 0 and destino:
        # Check stock
        disponible = get_central_qty(stock, item)
        if cantidad > disponible:
            flash(f"Stock insuficiente: hay {disponible} de {item}")
            return redirect(url_for("admin_stock"))

        # Transfer
        nuevo = disponible - cantidad
        if nuevo <= 0:
            stock["central"][item]["cantidad"] = 0
        else:
            stock["central"][item]["cantidad"] = nuevo

        if destino not in stock["sucursales"]:
            stock["sucursales"][destino] = {}
        stock["sucursales"][destino][item] = stock["sucursales"][destino].get(item, 0) + cantidad

        # Log transfer
        transfers.append({
            "fecha": datetime.datetime.now().isoformat(),
            "item": item,
            "cantidad": cantidad,
            "origen": "Central Dabra",
            "destino": destino,
            "usuario": session.get("nombre", ""),
        })

        save_stock(stock)
        save_transfers(transfers)
        registrar_movimiento(
            item=item,
            tipo="egreso",
            cantidad=cantidad,
            sucursal=destino,
            nota=f"Transferencia de Central a {destino}",
        )
        registrar_movimiento(
            item=item,
            tipo="ingreso",
            cantidad=cantidad,
            sucursal=destino,
            nota=f"Recepcion por transferencia desde Central",
        )
        flash(f"Transferido: {cantidad}x {item} → {destino}")

    return redirect(url_for("admin_stock"))


@app.route("/admin/stock/precio", methods=["POST"])
@admin_required
def stock_precio():
    stock = load_stock()
    item = request.form.get("item", "").strip()
    precio_raw = request.form.get("precio_unitario", "").strip().replace(",", ".")
    if not item:
        flash("Item no especificado")
        return redirect(url_for("admin_stock"))
    try:
        precio = float(precio_raw) if precio_raw else 0.0
    except ValueError:
        flash("Precio invalido")
        return redirect(url_for("admin_stock"))
    set_central_precio(stock, item, precio)
    save_stock(stock)
    flash(f"Precio actualizado: {item} → ${precio:,.2f}")
    return redirect(request.form.get("next") or url_for("admin_stock"))


@app.route("/admin/stock/item")
@login_required
def admin_stock_item():
    item = request.args.get("item", "").strip()
    if not item:
        flash("Item no especificado")
        return redirect(url_for("admin_stock"))

    stock = load_stock()
    stock_actual = get_central_qty(stock, item)
    precio_unitario = get_central_precio(stock, item)
    stock_sucursales = {
        suc: items.get(item, 0)
        for suc, items in stock.get("sucursales", {}).items()
        if items.get(item, 0) > 0
    }

    data = load_movimientos()
    movs = [m for m in data.get("movimientos", []) if m.get("item") == item]
    movs.sort(key=lambda m: m.get("fecha", ""), reverse=True)

    total_egresos = sum(m["cantidad"] for m in movs if m.get("tipo") == "egreso")
    total_ingresos = sum(m["cantidad"] for m in movs if m.get("tipo") == "ingreso")

    hoy = datetime.datetime.now()
    mes_actual = hoy.strftime("%Y-%m")
    movs_mes = sum(1 for m in movs if m.get("fecha", "").startswith(mes_actual))

    # Agrupar egresos por mes (YYYY-MM)
    por_mes = {}
    for m in movs:
        if m.get("tipo") != "egreso":
            continue
        ym = m.get("fecha", "")[:7]
        if not ym:
            continue
        por_mes[ym] = por_mes.get(ym, 0) + m.get("cantidad", 0)
    egresos_por_mes = sorted(por_mes.items())
    max_egreso_mes = max((c for _, c in egresos_por_mes), default=0)

    anios_disponibles = sorted({m.get("fecha", "")[:4] for m in movs if m.get("fecha")}, reverse=True)

    return render_template(
        "admin_stock_item.html",
        item=item,
        stock_actual=stock_actual,
        precio_unitario=precio_unitario,
        stock_sucursales=stock_sucursales,
        movimientos=movs,
        total_egresos=total_egresos,
        total_ingresos=total_ingresos,
        movs_mes=movs_mes,
        egresos_por_mes=egresos_por_mes,
        max_egreso_mes=max_egreso_mes,
        anios_disponibles=anios_disponibles,
    )


@app.route("/admin/stock/movimientos")
@login_required
def admin_stock_movimientos():
    data = load_movimientos()
    movs = list(data.get("movimientos", []))

    filtro_tipo = request.args.get("tipo", "").strip()
    filtro_item = request.args.get("item", "").strip()
    filtro_desde = request.args.get("desde", "").strip()
    filtro_hasta = request.args.get("hasta", "").strip()
    formato = request.args.get("formato", "").strip().lower()

    if filtro_tipo:
        movs = [m for m in movs if m.get("tipo") == filtro_tipo]
    if filtro_item:
        movs = [m for m in movs if filtro_item.lower() in m.get("item", "").lower()]
    if filtro_desde:
        movs = [m for m in movs if m.get("fecha", "")[:10] >= filtro_desde]
    if filtro_hasta:
        movs = [m for m in movs if m.get("fecha", "")[:10] <= filtro_hasta]

    movs.sort(key=lambda m: m.get("fecha", ""), reverse=True)

    if formato == "csv":
        import csv
        import io
        from flask import Response

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Fecha", "Tipo", "Item", "Cantidad", "Sucursal", "Ticket", "Nota"])
        for m in movs:
            writer.writerow([
                m.get("fecha", ""),
                m.get("tipo", ""),
                m.get("item", ""),
                m.get("cantidad", 0),
                m.get("sucursal", ""),
                m.get("ticket_id") or "",
                m.get("nota", ""),
            ])
        nombre = datetime.datetime.now().strftime("tecman_movimientos_%Y%m%d.csv")
        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": f"attachment;filename={nombre}"},
        )

    items_unicos = sorted({m.get("item", "") for m in data.get("movimientos", []) if m.get("item")})

    return render_template(
        "admin_stock_movimientos.html",
        movimientos=movs,
        filtro_tipo=filtro_tipo,
        filtro_item=filtro_item,
        filtro_desde=filtro_desde,
        filtro_hasta=filtro_hasta,
        items_unicos=items_unicos,
    )


# --- Routes: Comprobantes (facturas / remitos) ---

COMPROBANTE_EXTENSIONES = {".pdf", ".jpg", ".jpeg", ".png"}

DESTINOS_FIJOS = {
    "Dabra Central": "Colectora Panamericana KM 25.6, Don Torcuato, Buenos Aires",
    "Directorio": "Directorio (Av. Directorio) - CABA",
    "CD Garín": "CD Garín - Av. Mozart s/n, Garín",
    "Testai": "Testai - Av. General Paz y Ruta 8, San Martín",
}


def _destinos_sucursales():
    from sucursales_data import SUCURSALES_INFO
    items = []
    for num in sorted(SUCURSALES_INFO.keys()):
        info = SUCURSALES_INFO[num]
        tienda = info.get("tienda", "").strip()
        label = f"Suc {num} - {tienda}" if tienda else f"Suc {num}"
        partes = [p for p in (info.get("direccion", ""), info.get("ciudad", ""), info.get("provincia", "")) if p]
        items.append({"label": label, "direccion": ", ".join(partes)})
    return items


def _direccion_para_destino(destino):
    destino = (destino or "").strip()
    if not destino:
        return ""
    if destino in DESTINOS_FIJOS:
        return DESTINOS_FIJOS[destino]
    if destino.startswith("Suc "):
        from sucursales_data import SUCURSALES_INFO
        num = destino[4:].split("-", 1)[0].strip()
        info = SUCURSALES_INFO.get(num, {})
        partes = [p for p in (info.get("direccion", ""), info.get("ciudad", ""), info.get("provincia", "")) if p]
        return ", ".join(partes)
    return ""


@app.route("/admin/comprobantes")
@login_required
def admin_comprobantes():
    data = load_comprobantes()
    comprobantes = data.get("comprobantes", [])

    filtro_tipo = request.args.get("tipo", "").strip()
    filtro_proveedor = request.args.get("proveedor", "").strip().lower()
    filtro_desde = request.args.get("desde", "").strip()
    filtro_hasta = request.args.get("hasta", "").strip()
    ticket_pre = request.args.get("ticket_id", "").strip()

    filtrados = comprobantes
    if filtro_tipo:
        filtrados = [c for c in filtrados if c.get("tipo") == filtro_tipo]
    if filtro_proveedor:
        filtrados = [c for c in filtrados if filtro_proveedor in c.get("proveedor", "").lower()]
    if filtro_desde:
        filtrados = [c for c in filtrados if c.get("fecha", "") >= filtro_desde]
    if filtro_hasta:
        filtrados = [c for c in filtrados if c.get("fecha", "") <= filtro_hasta]

    filtrados.sort(key=lambda c: c.get("fecha", ""), reverse=True)

    total_monto = sum(float(c.get("monto", 0) or 0) for c in filtrados)
    total_facturas = sum(1 for c in filtrados if c.get("tipo") == "factura")
    total_remitos = sum(1 for c in filtrados if c.get("tipo") in ("remito", "remito_proveedor", "remito_interno"))

    proveedores_unicos = sorted(set(c.get("proveedor", "") for c in comprobantes if c.get("proveedor")))

    stock = load_stock()
    stock_items = sorted(stock.get("central", {}).keys())

    # Lista de sucursales para reingreso/devolucion
    sucursales_lista = sorted(set(
        t.get("sucursal", "") for t in load_tickets() if t.get("sucursal")
    ))

    destinos_sucursales = _destinos_sucursales()

    return render_template(
        "admin_comprobantes.html",
        comprobantes=filtrados,
        filtro_tipo=filtro_tipo,
        filtro_proveedor=filtro_proveedor,
        filtro_desde=filtro_desde,
        filtro_hasta=filtro_hasta,
        total_monto=total_monto,
        total_facturas=total_facturas,
        total_remitos=total_remitos,
        proveedores_unicos=proveedores_unicos,
        stock_items=stock_items,
        ticket_pre=ticket_pre,
        sucursales_lista=sucursales_lista,
        destinos_sucursales=destinos_sucursales,
        destinos_fijos=list(DESTINOS_FIJOS.keys()),
    )


@app.route("/admin/comprobantes/nuevo", methods=["POST"])
@login_required
def admin_comprobantes_nuevo():
    data = load_comprobantes()
    tipo = request.form.get("tipo", "").strip()
    numero = request.form.get("numero", "").strip()
    fecha = request.form.get("fecha", "").strip()

    destino = ""
    destino_direccion = ""
    retiro_tipo = ""
    retiro_detalle = ""

    if tipo == "remito_interno":
        destino = request.form.get("destino", "").strip()
        destino_direccion = request.form.get("destino_direccion", "").strip()
        if not destino_direccion:
            destino_direccion = _direccion_para_destino(destino)
        proveedor = destino or "Remito interno"
        retiro_tipo = request.form.get("retiro_tipo", "").strip()
        retiro_detalle = request.form.get("retiro_detalle", "").strip()
    else:
        origen_tipo = request.form.get("origen_tipo", "proveedor")
        if origen_tipo == "sucursal":
            proveedor = f"Reingreso — {request.form.get('sucursal_origen', '').strip()}"
        elif origen_tipo == "obra":
            proveedor = f"Obra — {request.form.get('obra_origen', '').strip()}"
        else:
            proveedor = request.form.get("proveedor", "").strip()
    monto_raw = request.form.get("monto", "").strip().replace(",", ".")
    # "comentario" es el alias nuevo de "descripcion" (UX simplificada)
    descripcion = (request.form.get("comentario") or request.form.get("descripcion") or "").strip()
    ticket_ids_raw = request.form.get("ticket_ids", "").strip()

    try:
        monto = float(monto_raw) if monto_raw else 0.0
    except ValueError:
        monto = 0.0

    ticket_ids = []
    for part in ticket_ids_raw.replace(";", ",").split(","):
        part = part.strip()
        if part.isdigit():
            ticket_ids.append(int(part))

    archivo = ""
    f = request.files.get("archivo")
    if f and f.filename:
        ext = Path(f.filename).suffix.lower()
        if ext in COMPROBANTE_EXTENSIONES:
            fname = f"{tipo or 'comp'}_{uuid.uuid4().hex[:10]}{ext}"
            f.save(str(COMPROBANTES_DIR / fname))
            archivo = fname
        else:
            flash("Formato de archivo no permitido (solo PDF, JPG, PNG)")
            return redirect(url_for("admin_comprobantes"))

    # Fecha por defecto: hoy (la factura simple puede no traerla)
    if not fecha:
        fecha = datetime.date.today().isoformat()

    # Auto-generar número si es factura y no se cargó
    if tipo == "factura" and not numero:
        numero = f"AUTO-{fecha}-{uuid.uuid4().hex[:6].upper()}"

    if not tipo or not fecha:
        flash("Seleccioná el tipo y la fecha del comprobante")
        return redirect(url_for("admin_comprobantes"))

    # Facturas: proveedor y número son opcionales (UX simple).
    # Remitos: mantienen la validación estricta.
    if tipo != "factura" and (not numero or not proveedor):
        flash("Complete número y proveedor del remito")
        return redirect(url_for("admin_comprobantes"))

    # Items asociados (items_factura): listas paralelas item_nombre[], item_cantidad[], item_precio[]
    items_factura = []
    item_names = request.form.getlist("item_nombre[]")
    item_cants = request.form.getlist("item_cantidad[]")
    item_precios = request.form.getlist("item_precio[]")
    stock_data = None
    # Pre-generamos el id del comprobante para poder referenciarlo en los lotes FIFO
    comprobante_id = uuid.uuid4().hex[:12]
    for idx, nombre in enumerate(item_names):
        nombre = (nombre or "").strip()
        if not nombre:
            continue
        try:
            cant = int(item_cants[idx]) if idx < len(item_cants) and item_cants[idx] else 0
        except ValueError:
            cant = 0
        try:
            precio = float((item_precios[idx] if idx < len(item_precios) else "0").replace(",", ".")) if item_precios[idx] else 0.0
        except (ValueError, IndexError):
            precio = 0.0
        if cant <= 0 and precio <= 0:
            continue
        items_factura.append({"item": nombre, "cantidad": cant, "precio_unitario": precio})
        # En facturas: sumar al stock central e impactar el precio_unitario del item
        if tipo == "remito_proveedor":
            # El remito de proveedor es el ingreso fisico real al deposito
            if stock_data is None:
                stock_data = load_stock()
            actual = get_central_qty(stock_data, nombre)
            nueva_cant = actual + cant if cant > 0 else actual
            set_central_qty(stock_data, nombre, nueva_cant, precio=precio if precio > 0 else None)
            if cant > 0:
                # Crear lote FIFO real atado al remito (trazabilidad contra factura/remito)
                crear_lote_fifo(
                    item=nombre,
                    cantidad=cant,
                    precio_unitario=precio,
                    tipo_origen="remito_proveedor",
                    comprobante_id=comprobante_id,
                    numero_comprobante=numero,
                    proveedor=proveedor,
                    fecha_origen=fecha,
                )
                registrar_movimiento(
                    item=nombre,
                    tipo="ingreso",
                    cantidad=cant,
                    sucursal="Central Dabra",
                    nota=f"Ingreso por remito {numero} ({proveedor})",
                    precio_unitario=precio if precio > 0 else None,
                    numero_comprobante_origen=numero,
                    proveedor_origen=proveedor,
                )
        elif tipo == "factura":
            # La factura solo actualiza el precio unitario (registro contable)
            # No suma al stock porque eso lo hace el remito
            if stock_data is None:
                stock_data = load_stock()
            if precio > 0:
                set_central_precio(stock_data, nombre, precio)
    if stock_data is not None:
        save_stock(stock_data)

    comprobante = {
        "id": comprobante_id,
        "tipo": tipo,
        "numero": numero,
        "fecha": fecha,
        "proveedor": proveedor,
        "monto": monto,
        "descripcion": descripcion,
        "ticket_ids": ticket_ids,
        "archivo": archivo,
        "items_factura": items_factura,
        "created_at": datetime.datetime.now().isoformat(),
        "cargado_por": session.get("nombre", ""),
    }
    if tipo == "remito_interno":
        comprobante["destino"] = destino
        comprobante["destino_direccion"] = destino_direccion
        comprobante["retiro_tipo"] = retiro_tipo
        comprobante["retiro_detalle"] = retiro_detalle
    if tipo == "remito_proveedor":
        comprobante["parcial"] = request.form.get("remito_parcial") == "1"
        comprobante["factura_asociada"] = request.form.get("factura_asociada", "").strip()
        comprobante["entrega"] = request.form.get("remito_entrega", "").strip()
    data.setdefault("comprobantes", []).append(comprobante)
    save_comprobantes(data)

    # Notificar a admins cuando hay ingreso de stock (remito de proveedor)
    if tipo == "remito_proveedor" and items_factura:
        autor = session.get("nombre", "?")
        total_unid = sum(int(it.get("cantidad", 0)) for it in items_factura)
        items_resumen = "\n".join(
            f"  • {it['item']}: {it['cantidad']} u." + (f" @ ${it['precio_unitario']:,.0f}" if it.get('precio_unitario') else "")
            for it in items_factura if it.get("cantidad", 0) > 0
        )
        parcial_tag = " (PARCIAL)" if comprobante.get("parcial") else ""
        titulo = f"📦 Ingreso de stock: remito {numero}{parcial_tag}"
        detalle = f"Proveedor: {proveedor}\nTotal unidades: {total_unid}\n\n{items_resumen}"
        if comprobante.get("factura_asociada"):
            detalle += f"\n\nFactura asociada: {comprobante['factura_asociada']}"
        agregar_notif_admin(titulo, detalle, tipo="stock_ingreso", autor=autor, link=url_for("admin_comprobantes"))
    elif tipo == "factura":
        autor = session.get("nombre", "?")
        agregar_notif_admin(
            f"📄 Factura cargada: {numero}",
            f"Proveedor: {proveedor}" + (f"\nMonto: ${monto:,.2f}" if monto else "") + (f"\nComentario: {descripcion}" if descripcion else ""),
            tipo="factura", autor=autor, link=url_for("admin_comprobantes")
        )

    flash(f"Comprobante registrado: {tipo} #{numero}" + (f" - {len(items_factura)} items" if items_factura else ""))
    return redirect(url_for("admin_comprobantes"))


@app.route("/admin/notif/<nid>/leer", methods=["POST"])
@login_required
def admin_notif_leer(nid):
    data = load_notif_admin()
    for n in data.get("notificaciones", []):
        if n.get("id") == nid:
            n["leida"] = True
            break
    save_notif_admin(data)
    return redirect(request.referrer or url_for("admin_panel"))


@app.route("/admin/notif/leer-todas", methods=["POST"])
@login_required
def admin_notif_leer_todas():
    data = load_notif_admin()
    for n in data.get("notificaciones", []):
        n["leida"] = True
    save_notif_admin(data)
    return redirect(request.referrer or url_for("admin_panel"))


@app.route("/admin/comprobantes/eliminar/<cid>", methods=["POST"])
@admin_required
def admin_comprobantes_eliminar(cid):
    data = load_comprobantes()
    antes = len(data.get("comprobantes", []))
    data["comprobantes"] = [c for c in data.get("comprobantes", []) if c.get("id") != cid]
    if len(data["comprobantes"]) < antes:
        save_comprobantes(data)
        flash("Comprobante eliminado")
    return redirect(url_for("admin_comprobantes"))


@app.route("/api/destino-direccion")
@admin_required
def api_destino_direccion():
    destino = request.args.get("destino", "").strip()
    return jsonify({"direccion": _direccion_para_destino(destino)})


@app.route("/admin/comprobantes/<cid>/imprimir")
@login_required
def admin_comprobantes_imprimir(cid):
    data = load_comprobantes()
    comp = next((c for c in data.get("comprobantes", []) if c.get("id") == cid), None)
    if not comp:
        return "Comprobante no encontrado", 404
    try:
        fecha_fmt = datetime.datetime.strptime(comp.get("fecha", ""), "%Y-%m-%d").strftime("%d/%m/%Y")
    except (ValueError, TypeError):
        fecha_fmt = comp.get("fecha", "")
    return render_template(
        "comprobante_imprimir.html",
        c=comp,
        fecha_fmt=fecha_fmt,
    )


# --- Routes: Contable (imputacion por sucursal) ---

def _tickets_imputados(tickets, desde="", hasta="", sucursal=""):
    out = []
    for t in tickets:
        if "imputacion_monto" not in t:
            continue
        if t.get("estado") not in ("Resuelto", "Cerrado"):
            continue
        fecha_imp = (t.get("imputacion_fecha") or t.get("actualizado") or t.get("creado") or "")[:10]
        if desde and fecha_imp < desde:
            continue
        if hasta and fecha_imp > hasta:
            continue
        if sucursal and t.get("sucursal") != sucursal:
            continue
        out.append(t)
    return out


@app.route("/admin/contable/reporte")
@admin_required
def admin_contable_reporte():
    tickets = load_tickets()
    desde = request.args.get("desde", "").strip()
    hasta = request.args.get("hasta", "").strip()
    sucursal = request.args.get("sucursal", "").strip()
    formato = request.args.get("formato", "").strip().lower()

    imputados = _tickets_imputados(tickets, desde=desde, hasta=hasta, sucursal=sucursal)

    # Agrupar por sucursal. Cada ticket puede expandirse a varias filas si su
    # imputacion consumio multiples lotes FIFO (una fila por lote consumido,
    # con subtotal parcial). Si el ticket no tiene trazabilidad FIFO (datos
    # viejos) se emite una fila unica marcada como sin trazabilidad.
    por_suc = {}
    for t in imputados:
        suc = t.get("sucursal", "Sin sucursal")
        fecha_imp = (t.get("imputacion_fecha") or t.get("actualizado") or t.get("creado") or "")[:10]
        item = t.get("imputacion_item", "")
        lotes = t.get("imputacion_lotes") or []
        sin_traza_ticket = bool(t.get("imputacion_sin_trazabilidad_fifo"))
        filas_ticket = []
        if lotes:
            for lote in lotes:
                cant = int(lote.get("cantidad", 0) or 0)
                precio = float(lote.get("precio_unitario", 0) or 0)
                filas_ticket.append({
                    "ticket_id": t.get("id"),
                    "item": item,
                    "cantidad": cant,
                    "precio_unitario": precio,
                    "subtotal": round(cant * precio, 2),
                    "fecha": fecha_imp,
                    "numero_comprobante_origen": lote.get("numero_comprobante", "") or "",
                    "proveedor_origen": lote.get("proveedor", "") or "",
                    "fecha_origen": lote.get("fecha_origen", "") or "",
                    "trazabilidad_fifo_ok": True,
                    "detalle_lotes": [lote],
                })
            if sin_traza_ticket:
                # Quedo un resto sin cubrir por lotes -> fila separada
                cant_lotes = sum(int(l.get("cantidad", 0) or 0) for l in lotes)
                monto_lotes = sum(
                    round(int(l.get("cantidad", 0) or 0) * float(l.get("precio_unitario", 0) or 0), 2)
                    for l in lotes
                )
                cant_total = int(t.get("imputacion_cantidad", 0) or 0)
                monto_total = float(t.get("imputacion_monto", 0) or 0)
                cant_resto = max(0, cant_total - cant_lotes)
                monto_resto = round(monto_total - monto_lotes, 2)
                if cant_resto > 0 or monto_resto > 0:
                    precio_resto = round(monto_resto / cant_resto, 4) if cant_resto > 0 else 0.0
                    filas_ticket.append({
                        "ticket_id": t.get("id"),
                        "item": item,
                        "cantidad": cant_resto,
                        "precio_unitario": precio_resto,
                        "subtotal": monto_resto,
                        "fecha": fecha_imp,
                        "numero_comprobante_origen": "",
                        "proveedor_origen": "",
                        "fecha_origen": "",
                        "trazabilidad_fifo_ok": False,
                        "detalle_lotes": [],
                    })
        else:
            filas_ticket.append({
                "ticket_id": t.get("id"),
                "item": item,
                "cantidad": int(t.get("imputacion_cantidad", 0) or 0),
                "precio_unitario": float(t.get("imputacion_precio_unitario", 0) or 0),
                "subtotal": float(t.get("imputacion_monto", 0) or 0),
                "fecha": fecha_imp,
                "numero_comprobante_origen": "",
                "proveedor_origen": "",
                "fecha_origen": "",
                "trazabilidad_fifo_ok": False,
                "detalle_lotes": [],
            })

        grupo = por_suc.setdefault(suc, {"items": [], "total": 0.0, "cantidad_items": 0})
        for fila in filas_ticket:
            grupo["items"].append(fila)
            grupo["total"] += fila["subtotal"]
            grupo["cantidad_items"] += int(fila["cantidad"] or 0)

    # Ordenar: sucursales por total desc, filas por fecha desc
    for g in por_suc.values():
        g["items"].sort(key=lambda x: x["fecha"], reverse=True)
    reporte = sorted(por_suc.items(), key=lambda kv: kv[1]["total"], reverse=True)

    total_general = sum(g["total"] for g in por_suc.values())

    if formato == "csv":
        import csv
        import io
        from flask import Response
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "Sucursal", "Fecha imputacion", "Ticket#", "Item",
            "Cantidad", "Precio Unit.", "Subtotal",
            "Factura/Remito origen", "Proveedor origen", "Fecha origen",
            "Trazabilidad FIFO",
        ])
        for suc_nom, grupo in reporte:
            for fila in grupo["items"]:
                writer.writerow([
                    suc_nom,
                    fila["fecha"],
                    fila["ticket_id"],
                    fila["item"],
                    fila["cantidad"],
                    f"{fila['precio_unitario']:.2f}",
                    f"{fila['subtotal']:.2f}",
                    fila.get("numero_comprobante_origen", ""),
                    fila.get("proveedor_origen", ""),
                    fila.get("fecha_origen", ""),
                    "OK" if fila.get("trazabilidad_fifo_ok") else "Sin trazabilidad historica",
                ])
        nombre = datetime.datetime.now().strftime("tecman_contable_%Y%m%d.csv")
        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": f"attachment;filename={nombre}"},
        )

    return render_template(
        "admin_contable.html",
        reporte=reporte,
        total_general=total_general,
        desde=desde,
        hasta=hasta,
        sucursal=sucursal,
        sucursales=SUCURSALES,
    )


@app.route("/admin/comprobantes/reporte")
@admin_required
def admin_comprobantes_reporte():
    import csv
    import io
    from flask import Response

    data = load_comprobantes()
    comprobantes = data.get("comprobantes", [])

    filtro_tipo = request.args.get("tipo", "").strip()
    filtro_proveedor = request.args.get("proveedor", "").strip().lower()
    filtro_desde = request.args.get("desde", "").strip()
    filtro_hasta = request.args.get("hasta", "").strip()

    if filtro_tipo:
        comprobantes = [c for c in comprobantes if c.get("tipo") == filtro_tipo]
    if filtro_proveedor:
        comprobantes = [c for c in comprobantes if filtro_proveedor in c.get("proveedor", "").lower()]
    if filtro_desde:
        comprobantes = [c for c in comprobantes if c.get("fecha", "") >= filtro_desde]
    if filtro_hasta:
        comprobantes = [c for c in comprobantes if c.get("fecha", "") <= filtro_hasta]

    comprobantes.sort(key=lambda c: c.get("fecha", ""))

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Fecha", "Tipo", "Numero", "Proveedor", "Monto", "Descripcion", "Tickets asociados", "Archivo"])
    for c in comprobantes:
        writer.writerow([
            c.get("fecha", ""),
            c.get("tipo", ""),
            c.get("numero", ""),
            c.get("proveedor", ""),
            c.get("monto", 0),
            c.get("descripcion", ""),
            ", ".join(str(x) for x in c.get("ticket_ids", [])),
            c.get("archivo", ""),
        ])
    output.seek(0)
    nombre = datetime.datetime.now().strftime("tecman_comprobantes_%Y%m%d.csv")
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment;filename={nombre}"},
    )


# --- Routes: Habilitaciones Municipales ---

def _parse_int_or_none(val):
    val = (val or "").strip()
    if not val:
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def _parse_float_or_none(val):
    val = (val or "").strip().replace(",", ".")
    if not val:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _calc_vencimiento(fecha_hab, anios):
    """Si tenemos fecha de habilitacion + anios, devolvemos vencimiento ISO."""
    if not fecha_hab or not anios:
        return ""
    try:
        base = datetime.date.fromisoformat(fecha_hab[:10])
        return base.replace(year=base.year + int(anios)).isoformat()
    except (ValueError, TypeError):
        return ""


@app.route("/admin/habilitaciones")
@admin_required
def admin_habilitaciones():
    data = load_habilitaciones()
    items = [_enrich_habilitacion(h) for h in data.get("habilitaciones", [])]

    # Agregar sucursales con estado en S&H pero sin registro detallado
    syh_data = load_syh()
    suc_con_detalle = {str(h.get("sucursal_num") or "").strip() for h in data.get("habilitaciones", [])}
    suc_con_detalle |= {str(h.get("sucursal", "")).replace("Sucursal ", "").strip() for h in data.get("habilitaciones", [])}
    ESTADO_SYH_MAP = {"Vigente": "vigente", "Por vencer": "por_vencer", "Vencida": "vencida"}
    for suc_num, sdata in syh_data.items():
        hab_syh = sdata.get("habilitacion", "")
        if hab_syh and hab_syh not in ("Sin datos", "") and suc_num not in suc_con_detalle:
            items.append({
                "id": f"syh_{suc_num}",
                "sucursal": f"Sucursal {suc_num}",
                "sucursal_num": suc_num,
                "municipio": "",
                "rubro": "",
                "numero_cert": "",
                "fecha_vencimiento": sdata.get("habilitacion_vencimiento", ""),
                "observaciones": "(Estado cargado desde S&H)",
                "estado": ESTADO_SYH_MAP.get(hab_syh, "sin_dato"),
                "_desde_syh": True,
            })

    filtro_estado = request.args.get("estado", "").strip()
    filtro_sucursal = request.args.get("sucursal", "").strip()
    filtro_q = request.args.get("q", "").strip().lower()

    filtrados = items
    if filtro_estado:
        filtrados = [h for h in filtrados if h["estado"] == filtro_estado]
    if filtro_sucursal:
        filtrados = [h for h in filtrados if h.get("sucursal") == filtro_sucursal]
    if filtro_q:
        def _match(h):
            campos = [
                h.get("sucursal", ""),
                h.get("municipio", ""),
                h.get("direccion", ""),
                h.get("numero_cert", ""),
                h.get("rubro", ""),
                h.get("observaciones", ""),
            ]
            return any(filtro_q in (c or "").lower() for c in campos)
        filtrados = [h for h in filtrados if _match(h)]

    filtrados.sort(key=lambda h: (
        ESTADO_HAB_ORDEN.get(h["estado"], 99),
        h.get("fecha_vencimiento", "9999-99-99") or "9999-99-99",
        h.get("sucursal", ""),
    ))

    stats = {
        "total": len(items),
        "vigentes": sum(1 for h in items if h["estado"] == "vigente"),
        "por_vencer": sum(1 for h in items if h["estado"] == "por_vencer"),
        "vencidas": sum(1 for h in items if h["estado"] == "vencida"),
        "sin_dato": sum(1 for h in items if h["estado"] == "sin_dato"),
    }

    sucursales_con_hab = sorted(set(h.get("sucursal", "") for h in items if h.get("sucursal")))

    return render_template(
        "admin_habilitaciones.html",
        habilitaciones=filtrados,
        stats=stats,
        sucursales=SUCURSALES,
        sucursales_con_hab=sucursales_con_hab,
        filtro_estado=filtro_estado,
        filtro_sucursal=filtro_sucursal,
        filtro_q=filtro_q,
    )


@app.route("/admin/habilitaciones/nuevo", methods=["POST"])
@admin_required
def admin_habilitaciones_nuevo():
    data = load_habilitaciones()
    sucursal = request.form.get("sucursal", "").strip()
    if not sucursal:
        flash("Seleccione una sucursal")
        return redirect(url_for("admin_habilitaciones"))

    suc_num = sucursal.replace("Sucursal ", "").strip()
    fecha_hab = request.form.get("fecha_habilitacion", "").strip()
    fecha_venc = request.form.get("fecha_vencimiento", "").strip()
    anios = _parse_int_or_none(request.form.get("vigencia_anios", ""))
    if not fecha_venc and fecha_hab and anios:
        fecha_venc = _calc_vencimiento(fecha_hab, anios)

    archivo = ""
    f = request.files.get("archivo")
    if f and f.filename:
        ext = Path(f.filename).suffix.lower()
        if ext in HABILITACION_EXTENSIONES:
            fname = f"hab_{suc_num or 'x'}_{uuid.uuid4().hex[:10]}{ext}"
            f.save(str(HABILITACIONES_DIR / fname))
            archivo = fname
        else:
            flash("Formato de archivo no permitido (solo PDF, JPG, PNG)")
            return redirect(url_for("admin_habilitaciones"))

    nueva = {
        "id": uuid.uuid4().hex[:12],
        "sucursal": sucursal,
        "sucursal_num": suc_num,
        "municipio": request.form.get("municipio", "").strip(),
        "direccion": request.form.get("direccion", "").strip(),
        "numero_cert": request.form.get("numero_cert", "").strip(),
        "fecha_habilitacion": fecha_hab,
        "fecha_vencimiento": fecha_venc,
        "vigencia_anios": anios,
        "rubro": request.form.get("rubro", "").strip(),
        "superficie_m2": _parse_float_or_none(request.form.get("superficie_m2", "")),
        "archivo": archivo,
        "observaciones": request.form.get("observaciones", "").strip(),
        "created_at": datetime.datetime.now().isoformat(),
        "cargado_por": session.get("nombre", ""),
    }
    data.setdefault("habilitaciones", []).append(nueva)
    save_habilitaciones(data)
    sync_alertas_syh()
    flash(f"Habilitación cargada para {sucursal}")
    return redirect(url_for("admin_habilitaciones"))


@app.route("/admin/habilitaciones/<hid>")
@admin_required
def admin_habilitaciones_detalle(hid):
    data = load_habilitaciones()
    h = next((x for x in data.get("habilitaciones", []) if x.get("id") == hid), None)
    if not h:
        return render_template("error.html", mensaje="Habilitación no encontrada"), 404
    return render_template(
        "admin_habilitaciones.html",
        habilitaciones=[_enrich_habilitacion(h)],
        detalle=_enrich_habilitacion(h),
        stats={"total": 1, "vigentes": 0, "por_vencer": 0, "vencidas": 0, "sin_dato": 0},
        sucursales=SUCURSALES,
        sucursales_con_hab=[],
        filtro_estado="",
        filtro_sucursal="",
        filtro_q="",
    )


@app.route("/admin/habilitaciones/<hid>/editar", methods=["POST"])
@admin_required
def admin_habilitaciones_editar(hid):
    data = load_habilitaciones()
    h = next((x for x in data.get("habilitaciones", []) if x.get("id") == hid), None)
    if not h:
        return render_template("error.html", mensaje="Habilitación no encontrada"), 404

    sucursal = request.form.get("sucursal", "").strip() or h.get("sucursal", "")
    suc_num = sucursal.replace("Sucursal ", "").strip()
    fecha_hab = request.form.get("fecha_habilitacion", "").strip()
    fecha_venc = request.form.get("fecha_vencimiento", "").strip()
    anios = _parse_int_or_none(request.form.get("vigencia_anios", ""))
    if not fecha_venc and fecha_hab and anios:
        fecha_venc = _calc_vencimiento(fecha_hab, anios)

    h["sucursal"] = sucursal
    h["sucursal_num"] = suc_num
    h["municipio"] = request.form.get("municipio", "").strip()
    h["direccion"] = request.form.get("direccion", "").strip()
    h["numero_cert"] = request.form.get("numero_cert", "").strip()
    h["fecha_habilitacion"] = fecha_hab
    h["fecha_vencimiento"] = fecha_venc
    h["vigencia_anios"] = anios
    h["rubro"] = request.form.get("rubro", "").strip()
    h["superficie_m2"] = _parse_float_or_none(request.form.get("superficie_m2", ""))
    h["observaciones"] = request.form.get("observaciones", "").strip()
    h["actualizado_por"] = session.get("nombre", "")
    h["actualizado"] = datetime.datetime.now().isoformat()

    f = request.files.get("archivo")
    if f and f.filename:
        ext = Path(f.filename).suffix.lower()
        if ext in HABILITACION_EXTENSIONES:
            fname = f"hab_{suc_num or 'x'}_{uuid.uuid4().hex[:10]}{ext}"
            f.save(str(HABILITACIONES_DIR / fname))
            h["archivo"] = fname

    save_habilitaciones(data)
    sync_alertas_syh()
    flash("Habilitación actualizada")
    return redirect(url_for("admin_habilitaciones"))


@app.route("/admin/habilitaciones/<hid>/eliminar", methods=["POST"])
@admin_required
def admin_habilitaciones_eliminar(hid):
    data = load_habilitaciones()
    antes = len(data.get("habilitaciones", []))
    data["habilitaciones"] = [x for x in data.get("habilitaciones", []) if x.get("id") != hid]
    if len(data["habilitaciones"]) < antes:
        save_habilitaciones(data)
        sync_alertas_syh()
        flash("Habilitación eliminada")
    return redirect(url_for("admin_habilitaciones"))


@app.route("/admin/habilitaciones/reporte")
@admin_required
def admin_habilitaciones_reporte():
    import csv
    import io
    from flask import Response

    data = load_habilitaciones()
    items = [_enrich_habilitacion(h) for h in data.get("habilitaciones", [])]
    items.sort(key=lambda h: (
        ESTADO_HAB_ORDEN.get(h["estado"], 99),
        h.get("fecha_vencimiento", "") or "",
        h.get("sucursal", ""),
    ))

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Sucursal", "Municipio", "Dirección", "N° Certificado",
        "Fecha habilitación", "Fecha vencimiento", "Vigencia (años)",
        "Rubro", "Superficie m²", "Estado", "Archivo", "Observaciones",
    ])
    for h in items:
        writer.writerow([
            h.get("sucursal", ""),
            h.get("municipio", ""),
            h.get("direccion", ""),
            h.get("numero_cert", ""),
            h.get("fecha_habilitacion", ""),
            h.get("fecha_vencimiento", ""),
            h.get("vigencia_anios", "") or "",
            h.get("rubro", ""),
            h.get("superficie_m2", "") or "",
            h.get("estado", ""),
            h.get("archivo", ""),
            h.get("observaciones", ""),
        ])
    nombre = datetime.datetime.now().strftime("tecman_habilitaciones_%Y%m%d.csv")
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment;filename={nombre}"},
    )


@app.route("/uploads/habilitaciones/<filename>")
@any_session_required
def serve_habilitacion(filename):
    return send_from_directory(str(HABILITACIONES_DIR), filename)


@app.route("/uploads/syh/<filename>")
@any_session_required
def serve_syh_upload(filename):
    return send_from_directory(str(UPLOADS_DIR), filename)


# --- API ---

@app.route("/api/categorias")
def api_categorias():
    cat = request.args.get("categoria", "")
    return jsonify(CATEGORIAS.get(cat, []))


@app.route("/guia-luminaria")
def guia_luminaria():
    return render_template("guia_luminaria.html")


@app.route("/static/uploads/guias/<filename>")
@any_session_required
def serve_guia(filename):
    return send_from_directory(str(GUIAS_DIR), filename)


@app.route("/admin/syh/borrar-doc", methods=["POST"])
@admin_required
def admin_syh_borrar_doc():
    """Borra documentos de syh.json que coincidan con filtros."""
    suc_num = request.form.get("suc_num", "").strip()
    contiene = request.form.get("contiene", "").strip().lower()
    archivo = request.form.get("archivo", "").strip()

    data = load_syh()
    total_borrados = 0

    sucs = [suc_num] if suc_num else list(data.keys())
    for s in sucs:
        if s not in data:
            continue
        docs = data[s].get("documentos_detallados", [])
        antes = len(docs)
        if contiene:
            docs = [d for d in docs if contiene not in (d.get("nombre") or "").lower()]
        if archivo:
            docs = [d for d in docs if d.get("archivo") != archivo]
        data[s]["documentos_detallados"] = docs
        total_borrados += antes - len(docs)

    save_syh(data)
    flash(f"Se eliminaron {total_borrados} documento(s) de S&H.")
    return redirect(url_for("admin_syh_docs"))


@app.route("/admin/syh/docs")
@admin_required
def admin_syh_docs():
    """Lista todos los documentos S&H para gestión."""
    suc_num = request.args.get("suc", "222")
    data = load_syh()
    suc_data = data.get(suc_num, {})
    docs = suc_data.get("documentos_detallados", [])
    sucs_con_docs = sorted([s for s in data if data[s].get("documentos_detallados")])
    return render_template("admin_syh_docs.html", docs=docs, suc_num=suc_num, sucs_con_docs=sucs_con_docs)


@app.route("/admin/syh/limpiar-222", methods=["POST"])
@admin_required
def admin_syh_limpiar_222():
    """Limpieza puntual: borra docs específicos de S&H."""
    data = load_syh()
    resumen = []

    filtros_globales = ["reg cap 2019", "greg cap 2019"]
    filtros_222 = ["moron municipal", "morón municipal", "informe"]

    for suc_num, suc_data in data.items():
        docs = suc_data.get("documentos_detallados", [])
        antes = len(docs)
        filtros = filtros_globales + (filtros_222 if suc_num == "222" else [])
        docs = [d for d in docs if not any(f in (d.get("nombre") or "").lower() for f in filtros)]
        data[suc_num]["documentos_detallados"] = docs
        borrados = antes - len(docs)
        if borrados:
            resumen.append(f"Suc {suc_num}: {borrados} borrado(s)")

    save_syh(data)
    flash("Limpieza completada. " + " | ".join(resumen) if resumen else "No se encontraron documentos a borrar.")
    return redirect(url_for("admin_panel"))


@app.route("/admin/fix-asignacion-ceyh", methods=["POST"])
@admin_required
def fix_asignacion_ceyh():
    tickets = load_tickets()
    cambiados = []
    for t in tickets:
        if t.get("asignado") not in ("Agustin Brahim", "Agustín Brahim", ASIGNACION_DEFAULT):
            continue
        if t.get("estado") in ("Cerrado", "Resuelto"):
            continue
        suc_nombre = t.get("sucursal", "")
        suc_num = suc_nombre.replace("Sucursal ", "").strip()
        proveedor = get_proveedor_abono_sucursal(suc_num)
        if proveedor:
            t["asignado"] = proveedor
            cambiados.append(t["id"])
    save_tickets(tickets)
    flash(f"Reasignados {len(cambiados)} tickets al proveedor de abono: {cambiados}")
    return redirect(url_for("admin_panel"))


@app.route("/api/resumen")
def api_resumen():
    secret = os.environ.get("BACKUP_SECRET", "")
    if not secret or request.args.get("token") != secret:
        return Response("Forbidden", status=403)
    tickets = load_tickets()
    hoy = datetime.date.today().isoformat()
    ayer = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    nuevos = [t for t in tickets if t.get("estado") == "Nuevo"]
    en_progreso = [t for t in tickets if t.get("estado") == "En progreso"]
    resueltos_hoy = [t for t in tickets if t.get("estado") == "Resuelto" and (t.get("fecha_cierre") or "")[:10] == hoy]
    urgentes = [t for t in tickets if t.get("prioridad") in (1, "1") and t.get("estado") not in ("Resuelto", "Cerrado")]
    nuevos_hoy = [t for t in nuevos if (t.get("fecha") or "")[:10] >= ayer]
    def mini(t):
        return {"id": t.get("id"), "sucursal": t.get("sucursal"), "categoria": t.get("categoria"), "subcategoria": t.get("subcategoria"), "prioridad": t.get("prioridad"), "fecha": (t.get("fecha") or "")[:10]}
    alertas = load_alertas_syh().get("alertas", [])
    alertas_mat = [a for a in alertas if a.get("tipo_alerta") != "habilitacion" and a.get("estado") in ("Vencidos", "Próximo a vencer")]
    alertas_hab = [a for a in alertas if a.get("tipo_alerta") == "habilitacion" and a.get("estado") in ("Vencida", "Próxima a vencer")]
    def mini_alerta(a):
        return {"sucursal": a.get("sucursal_num"), "estado": a.get("estado"), "tipos": a.get("tipos"), "proximo_vto": a.get("proximo_vto")}
    return jsonify({
        "fecha": hoy,
        "totales": {"nuevos": len(nuevos), "en_progreso": len(en_progreso), "urgentes": len(urgentes), "total_abiertos": len(nuevos) + len(en_progreso)},
        "nuevos_ultimas_24h": [mini(t) for t in nuevos_hoy],
        "urgentes": [mini(t) for t in urgentes[:10]],
        "en_progreso": [mini(t) for t in en_progreso[:15]],
        "resueltos_hoy": len(resueltos_hoy),
        "alertas_matafuegos": [mini_alerta(a) for a in alertas_mat],
        "alertas_habilitaciones": [mini_alerta(a) for a in alertas_hab],
    })


@app.route("/api/mails-resumen")
def api_mails_resumen():
    secret = os.environ.get("BACKUP_SECRET", "")
    if not secret or request.args.get("token") != secret:
        return Response("Forbidden", status=403)
    try:
        import imaplib
        import email
        from email.header import decode_header
        horas = int(request.args.get("horas", 24))
        since = (datetime.datetime.utcnow() - datetime.timedelta(hours=horas)).strftime("%d-%b-%Y")
        M = imaplib.IMAP4_SSL("imap.gmail.com", 993)
        M.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        M.select("INBOX")
        _, data = M.search(None, f'(SINCE "{since}" NOT FROM "{GMAIL_USER}")')
        ids = data[0].split()[-30:]
        mails = []
        for uid in ids:
            _, msg_data = M.fetch(uid, "(RFC822.HEADER)")
            msg = email.message_from_bytes(msg_data[0][1])
            def _decode(val):
                parts = decode_header(val or "")
                return "".join(p.decode(enc or "utf-8") if isinstance(p, bytes) else p for p, enc in parts)
            mails.append({
                "from": _decode(msg.get("From", "")),
                "subject": _decode(msg.get("Subject", "")),
                "date": msg.get("Date", ""),
                "snippet": "",
                "id": uid.decode()
            })
        M.logout()
        return jsonify({"total": len(mails), "mails": mails})
    except Exception as e:
        return jsonify({"error": str(e), "total": 0, "mails": []})


@app.route("/api/backup-data")
def api_backup_data():
    secret = os.environ.get("BACKUP_SECRET", "")
    if not secret or request.args.get("token") != secret:
        return Response("Forbidden", status=403)
    buf = io.BytesIO()
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in DATA_DIR.glob("*.json"):
            zf.write(f, f.name)
    buf.seek(0)
    filename = f"tecman-data-{ts}.zip"
    return Response(
        buf.read(),
        mimetype="application/zip",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.errorhandler(500)
def internal_error(e):
    return render_template("500.html"), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5050, debug=not IS_CLOUD)
