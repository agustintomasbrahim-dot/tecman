"""Tecman - Sistema de tickets de mantenimiento para Grupo Dabra"""

import os
import json
import uuid
import datetime
import shutil
from pathlib import Path
from functools import wraps

from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, send_from_directory

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "tecman-dev-key-2026")

IS_CLOUD = os.environ.get("RENDER", False)

# En Render usamos el disco persistente montado en /data
# En local usamos ./data relativo al proyecto
if IS_CLOUD and Path("/data").exists():
    DATA_DIR = Path("/data")
else:
    DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)

TICKETS_FILE = DATA_DIR / "tickets.json"
STOCK_FILE = DATA_DIR / "stock.json"
TRANSFERS_FILE = DATA_DIR / "transfers.json"
COMPROBANTES_FILE = DATA_DIR / "comprobantes.json"
NOTIF_ADMIN_FILE = DATA_DIR / "notif_admin.json"
STOCK_MOV_FILE = DATA_DIR / "stock_movimientos.json"
GUIAS_COUNTER_FILE = DATA_DIR / "guias_counter.json"
HABILITACIONES_FILE = DATA_DIR / "habilitaciones.json"

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

# --- Data ---

SUCURSALES = [
    "Central - Dabra", "Garin",
    "Sucursal 011", "Sucursal 014", "Sucursal 023", "Sucursal 028",
    "Sucursal 035", "Sucursal 036", "Sucursal 043", "Sucursal 049",
    "Sucursal 051", "Sucursal 052", "Sucursal 053", "Sucursal 054",
    "Sucursal 058", "Sucursal 065", "Sucursal 076", "Sucursal 077",
    "Sucursal 078", "Sucursal 080", "Sucursal 082", "Sucursal 083",
    "Sucursal 091", "Sucursal 092", "Sucursal 102", "Sucursal 111",
    "Sucursal 114", "Sucursal 120", "Sucursal 121", "Sucursal 123",
    "Sucursal 124", "Sucursal 125", "Sucursal 126", "Sucursal 128",
    "Sucursal 132", "Sucursal 133", "Sucursal 134", "Sucursal 135",
    "Sucursal 139", "Sucursal 141", "Sucursal 142", "Sucursal 145",
    "Sucursal 146", "Sucursal 147", "Sucursal 148", "Sucursal 156",
    "Sucursal 157", "Sucursal 158", "Sucursal 159", "Sucursal 160",
    "Sucursal 165", "Sucursal 166", "Sucursal 167", "Sucursal 170",
    "Sucursal 171", "Sucursal 172", "Sucursal 173", "Sucursal 176",
    "Sucursal 177", "Sucursal 178", "Sucursal 183", "Sucursal 184",
    "Sucursal 185", "Sucursal 186", "Sucursal 187", "Sucursal 188",
    "Sucursal 190", "Sucursal 191", "Sucursal 192", "Sucursal 193",
    "Sucursal 194", "Sucursal 196", "Sucursal 198", "Sucursal 199",
    "Sucursal 200", "Sucursal 202", "Sucursal 203", "Sucursal 204",
    "Sucursal 205", "Sucursal 206", "Sucursal 207", "Sucursal 208",
    "Sucursal 209", "Sucursal 211", "Sucursal 212", "Sucursal 213",
    "Sucursal 214", "Sucursal 215", "Sucursal 216", "Sucursal 217",
    "Sucursal 220", "Sucursal 221", "Sucursal 222", "Sucursal 224",
    "Sucursal 226", "Sucursal 229", "Sucursal 230", "Sucursal 231",
    "Sucursal 233", "Sucursal 234", "Sucursal 235", "Sucursal 236",
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
    "Otro": ["Otro"],
}

PRIORIDADES = {
    1: "Urgente",
    2: "Alta",
    3: "Media",
    4: "Baja",
}

ESTADOS = ["Nuevo", "Abierto", "En progreso", "Pendiente", "Resuelto", "Cerrado"]

ADMINS = {
    "agustin": {"password": "tecman2026", "nombre": "Agustín Brahim", "rol": "admin"},
    "carolina": {"password": "tecman2026", "nombre": "Carolina", "rol": "admin"},
    "jonathan": {"password": "tecman2026", "nombre": "Jonathan", "rol": "tecnico"},
    "patricia": {"password": "tecman2026", "nombre": "Patricia", "rol": "syh"},
    "rita": {"password": "tecman2026", "nombre": "Rita", "rol": "admin"},
}

# Portal de Compras (Laura). Portal separado del de admin.
COMPRAS_USERS = {
    "laura": {"password": "compras2026", "nombre": "Laura", "rol": "compras"},
}

# Portal Equipo de Mantenimiento Central (Hector y Jose)
EQUIPO_USERS = {
    "equipo": {"password": "central2026", "nombre": "Equipo Central", "rol": "equipo_central"},
}

SYH_FILE = DATA_DIR / "syh.json"

SYH_ESTADOS = {
    "habilitacion": ["Vigente", "Vencida", "En tramite", "Sin habilitacion"],
    "bomberos": ["Aprobado", "Pendiente", "Vencido", "Sin tramitar"],
    "matafuegos": ["Al dia", "Proximo a vencer", "Vencidos", "Sin datos"],
    "plano_evacuacion": ["Tiene", "No tiene"],
    "senalizacion": ["Completa", "Incompleta", "Sin datos"],
}

def load_syh():
    if SYH_FILE.exists():
        return json.loads(SYH_FILE.read_text())
    return {}

def save_syh(data):
    SYH_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))

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
    if STOCK_FILE.exists():
        data = json.loads(STOCK_FILE.read_text())
    else:
        data = {"central": {}, "sucursales": {}}
    central = data.get("central", {}) or {}
    for k in list(central.keys()):
        central[k] = _stock_entry(central[k])
    data["central"] = central
    data.setdefault("sucursales", {})
    return data


def save_stock(data):
    STOCK_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))


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
    if TRANSFERS_FILE.exists():
        return json.loads(TRANSFERS_FILE.read_text())
    return []

def save_transfers(data):
    TRANSFERS_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))

def load_comprobantes():
    if COMPROBANTES_FILE.exists():
        return json.loads(COMPROBANTES_FILE.read_text())
    return {"comprobantes": []}

def save_comprobantes(data):
    COMPROBANTES_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def load_notif_admin():
    if NOTIF_ADMIN_FILE.exists():
        return json.loads(NOTIF_ADMIN_FILE.read_text())
    return {"notificaciones": []}


def save_notif_admin(data):
    NOTIF_ADMIN_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))


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
    if STOCK_MOV_FILE.exists():
        return json.loads(STOCK_MOV_FILE.read_text())
    return {"movimientos": []}

def save_movimientos(data):
    STOCK_MOV_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))

def _load_guias_counter():
    if GUIAS_COUNTER_FILE.exists():
        try:
            return json.loads(GUIAS_COUNTER_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {"ultimo": 87889}

def _save_guias_counter(data):
    GUIAS_COUNTER_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))

def load_habilitaciones():
    if HABILITACIONES_FILE.exists():
        try:
            return json.loads(HABILITACIONES_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {"habilitaciones": []}

def save_habilitaciones(data):
    HABILITACIONES_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))

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


def registrar_movimiento(item, tipo, cantidad, sucursal="", ticket_id=None, nota="", monto_imputado=None, precio_unitario=None, area=None, envio_id=None):
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
    data.setdefault("movimientos", []).append(mov)
    save_movimientos(data)

# Sucursal login: each sucursal has a unique password
SUCURSAL_USERS = {}
for suc in SUCURSALES:
    # Extract number or key from name
    if "Sucursal" in suc:
        num = suc.replace("Sucursal ", "")
        SUCURSAL_USERS[f"suc{num}"] = {"password": f"mto{num}", "sucursal": suc}
    elif suc == "Central - Dabra":
        SUCURSAL_USERS["central"] = {"password": "mtocentral", "sucursal": suc}
    elif suc == "Garin":
        SUCURSAL_USERS["garin"] = {"password": "mtogarin", "sucursal": suc}

# Auto-assignment rules
ASIGNACION_DEFAULT = "Agustín Brahim"

# Sucursales por zona para asignación automática
SUCS_CORDOBA = {"076","078","123","124","203","215","224","233"}
SUCS_NOA = {"120","126","128","135","139","146","158","173","191","193","212","229","230","234","235"}
SUCS_MENDOZA = {"128","132","145","206","207","236"}
SUCS_SANJUAN = {"159","172"}

# Proveedor login
PROVEEDOR_USERS = {
    "ceyh": {"password": "prov2026", "nombre": "CEYH"},
    "gustavo": {"password": "prov2026", "nombre": "Gustavo Avellaneda"},
    "fuga": {"password": "prov2026", "nombre": "Julio Fuga (JRF)"},
    "ismael": {"password": "prov2026", "nombre": "Ismael Allende (JRF)"},
    "escalmeca": {"password": "prov2026", "nombre": "Escalmeca / Mauricio"},
    "adriel": {"password": "prov2026", "nombre": "Adriel (Pintor)"},
    "oscar": {"password": "prov2026", "nombre": "Oscar San Juan"},
    "jose": {"password": "prov2026", "nombre": "Jose Sanchez"},
    "blanco": {"password": "prov2026", "nombre": "Gustavo Blanco"},
    "nestor": {"password": "prov2026", "nombre": "Nestor Raul Diaz"},
    "federico": {"password": "prov2026", "nombre": "Federico Confort"},
    "javier": {"password": "prov2026", "nombre": "Javier"},
    "nicolas": {"password": "prov2026", "nombre": "Nicolas Audio"},
    "frattini": {"password": "prov2026", "nombre": "Cesar Frattini (No Bugs)"},
    "polaris": {"password": "prov2026", "nombre": "Polaris"},
    "astronovo": {"password": "prov2026", "nombre": "Astronovo"},
    "geronimo": {"password": "prov2026", "nombre": "Geronimo - Leo"},
    "croacia": {"password": "prov2026", "nombre": "Croacia"},
    "microglobal": {"password": "prov2026", "nombre": "Martin Microglobal"},
}

# Proveedores database
PROVEEDORES = [
    {"nombre": "Personal Mto. (camionetas propias)", "zona": "AMBA", "tipo": "General", "tel": "-", "sucursales": ["011","014","023","028","035","036","043","051","052","053","054","058","065","077","080","082","083","102","111","141","147","148","165","167","170","171","176","177","184","185","186","188","190","192","194","196","198","202","208","209","211","214","217","222","228"], "monto": "Recurso propio (2 camionetas, 2 tecnicos FT, 1 PT)", "incluye": "Mantenimiento general CABA/GBA", "no_incluye": "-"},
    {"nombre": "CEYH", "zona": "AMBA", "tipo": "General + AA", "tel": "11 3205-3759", "contacto": "Gaston", "fijo": True, "sucursales": ["023","028","035","054","058","077","082","083","092","141","157","165","167","170","176","177","184","188","195","196","200","202","209","213","214","216","222","223","238"], "monto": "$30.000.000 + IVA/mes", "incluye": "3 moviles (2 AA + 1 gral), 9hs L-V, 2 tecnicos por movil, mano de obra, supervision, vehiculo, herramientas", "no_incluye": "Materiales, consumibles. Fuera de horario se cobra aparte (min 3hs por movil)"},
    {"nombre": "Martin Microglobal", "zona": "AMBA", "tipo": "General", "tel": "11 5410-6488", "contacto": "Martin", "fijo": False, "sucursales": ["011","023","036","077","147","176","177","183","186","198","209","211","213","222","223","234"]},
    {"nombre": "Angel JYS", "zona": "AMBA", "tipo": "General", "tel": "113560-9316", "sucursales": ["Zona Norte AMBA"]},
    {"nombre": "Jorge (Limpieza vidrios)", "zona": "AMBA", "tipo": "Limpieza", "tel": "115182-7823", "sucursales": ["AMBA general"]},
    {"nombre": "Polaris", "zona": "AMBA", "tipo": "General", "tel": "11 6527-7128", "contacto": "Lucas", "fijo": True, "sucursales": ["171","183","184"]},
    {"nombre": "Astronovo AM", "zona": "AMBA", "tipo": "General", "tel": "11 5182-3968", "contacto": "Dylan", "fijo": True, "sucursales": ["186"]},
    {"nombre": "Astronovo HV", "zona": "AMBA", "tipo": "General", "tel": "11 3813-9215", "contacto": "Horacio", "fijo": True, "sucursales": ["176"]},
    {"nombre": "Escalmeca / Mauricio", "zona": "AMBA", "tipo": "Escaleras mecanicas", "tel": "115308-9834", "sucursales": ["183","184","186"], "monto": "$688.000 + IVA/mes", "incluye": "Mantenimiento preventivo de 8 escaleras mecanicas en 3 sucursales, lubricacion, engrase, limpieza, desarme parcial", "no_incluye": "-"},
    {"nombre": "L&G (Geronimo)", "zona": "AMBA", "tipo": "Tecnicos", "tel": "54 9 2236 69-2804", "contacto": "Geronimo", "fijo": False, "sucursales": ["092","217","239","240"]},
    {"nombre": "Sergio Marmol", "zona": "AMBA", "tipo": "Aire Acondicionado", "tel": "-", "sucursales": ["141"]},
    {"nombre": "Nicolas Audio", "zona": "Nacional", "tipo": "Audio", "tel": "-", "sucursales": ["036","049","053","065","077","083","091","092","125","127","128","141","148","156","165","166","167","176","177","183","186","194","200","202","210","211","213","216","226"]},
    {"nombre": "Gustavo Avellaneda", "zona": "Cordoba", "tipo": "General", "tel": "0351-320-1198", "sucursales": ["076","078","123","124","203","215","224","233"], "monto": "$1.800.000/mes", "incluye": "Limpieza canaletas/techos, filtros AA, destapes, plomeria menor, albañileria menor, pintura menor, luminarias, cerraduras, arranque semanal generadores, mantenimiento AA planificado", "no_incluye": "Combustible, pintura grande, zingueria, techos, albañileria mayor"},
    {"nombre": "Adriel (Pintor)", "zona": "Cordoba", "tipo": "Pintura", "tel": "351-860-2101", "sucursales": ["076","078","123","124","203","215","233"]},
    {"nombre": "Julio Fuga (JRF)", "zona": "NOA", "tipo": "Electrico + AA + Gral", "tel": "0381-454-5659", "sucursales": ["120","126","128","135","139","146","158","173","191","193","212","229","230","234","235"], "monto": "$2.050.000 + IVA/mes", "incluye": "Mto electrico preventivo (luminarias, tableros, bornes, termicas), mto AA (filtros, evaporadora, condensadora, desagues, plaquetas), 3 personas/visita, 2 urgencias/mes/suc", "no_incluye": "-"},
    {"nombre": "Ismael Allende (JRF)", "zona": "Mendoza/San Luis", "tipo": "Electrico + AA + Gral", "tel": "0261-664-3429", "sucursales": ["128","132","145","206","207","236"], "monto": "$1.200.000 + IVA/mes", "incluye": "Mto electrico preventivo, mto AA, plomeria, gral. 3 personas/visita, 2 urgencias/mes/suc", "no_incluye": "-"},
    {"nombre": "Oscar San Juan", "zona": "San Juan", "tipo": "General", "tel": "0264-498-5365", "sucursales": ["159","172"]},
    {"nombre": "Jose Sanchez", "zona": "San Juan", "tipo": "General", "tel": "0264-504-1961", "sucursales": ["159","172"]},
    {"nombre": "Gustavo Blanco", "zona": "Chaco/Corrientes", "tipo": "General", "tel": "379-434-7529", "sucursales": ["220","224"]},
    {"nombre": "Majo", "zona": "Chaco/Corrientes", "tipo": "General", "tel": "-", "sucursales": ["220","224"]},
    {"nombre": "Nestor Raul Diaz", "zona": "Neuquen", "tipo": "General", "tel": "299-418-7955", "sucursales": ["133"]},
    {"nombre": "Federico Confort", "zona": "Neuquen", "tipo": "General", "tel": "299-418-7955", "contacto": "Federico", "fijo": True, "sucursales": ["178","210"]},
    {"nombre": "Javier", "zona": "Santa Fe", "tipo": "General", "tel": "342-478-0031", "sucursales": ["226"]},
    {"nombre": "Liliana (Paisajista)", "zona": "AMBA", "tipo": "Paisajismo", "tel": "115872-4697", "sucursales": ["222"]},
    {"nombre": "Cesar Frattini (No Bugs)", "zona": "AMBA", "tipo": "Fumigaciones", "tel": "114474-9457", "sucursales": ["165","183","200","208","209","211","213","214","221","222"], "monto": "Por servicio", "incluye": "Fumigacion, urgencias bonificadas", "no_incluye": "-"},
    {"nombre": "Gerardo Goog", "zona": "AMBA", "tipo": "Fumigaciones", "tel": "115851-5565", "sucursales": ["052","167","187"]},
    {"nombre": "Pablo Norsuply", "zona": "AMBA", "tipo": "Insumos", "tel": "115923-5320", "sucursales": ["AMBA general"]},
    {"nombre": "Cesar Avalos (Prov. varios)", "zona": "Nacional", "tipo": "Varios", "tel": "116433-6302", "sucursales": ["091","114","116","126","127","166","178","210","214","226"]},
    {"nombre": "Croacia", "zona": "AMBA", "tipo": "Urgencias persianas", "tel": "11 3663-6408", "contacto": "Raquel", "fijo": False, "sucursales": ["AMBA general"]},
    {"nombre": "Home Pro", "zona": "AMBA", "tipo": "General", "tel": "11 4416-3911", "contacto": "Nicolas", "fijo": False, "sucursales": ["AMBA eventual"]},
    {"nombre": "Nivelar Construcciones", "zona": "Chaco/Corrientes", "tipo": "Construccion", "tel": "54 9 364 430-2787", "contacto": "Maria Jose", "fijo": False, "sucursales": ["220","224"]},
    {"nombre": "Conex", "zona": "Neuquen", "tipo": "General", "tel": "54 9 2995 57-5495", "contacto": "Rodrigo", "fijo": False, "sucursales": ["160","233","133","134","231"]},
    {"nombre": "Atila Generaciones", "zona": "AMBA", "tipo": "Grupos electrogenos", "tel": "115318-3306", "contacto": "Waldo", "fijo": True, "sucursales": ["195","208","211","Garin"]},
    {"nombre": "Layerenza Cortinas", "zona": "Cordoba", "tipo": "Cortinas", "tel": "351-545-1732", "fijo": False, "sucursales": ["076","078","123","124","203","215","233"]},
    # --- Proveedores de fumigacion por sucursal ---
    {"nombre": "Cesar Ricardo Fratini", "zona": "Nacional", "tipo": "Fumigaciones", "tel": "-", "fijo": False, "sucursales": ["014","020","028","035","036","049","053","054","102","111","121","125","141","147","148","156","157","165","170","176","177","183","184","185","186","190","192","196","198","199","200","202","208","213","214","219","221","228","234","237","238"]},
    {"nombre": "INGAM Control de Plagas SRL", "zona": "Nacional", "tipo": "Fumigaciones", "tel": "-", "contacto": "Fernando", "fijo": False, "sucursales": ["065","077","080","082","083","142","173","188","191","194","195","209","211","216","230"]},
    {"nombre": "David Esteban Medina", "zona": "Cordoba", "tipo": "Fumigaciones", "tel": "-", "fijo": False, "sucursales": ["076","078","123","124","203","215","233"]},
    {"nombre": "RC Mansilla SA (El Gallo)", "zona": "AMBA", "tipo": "Fumigaciones", "tel": "-", "fijo": False, "sucursales": ["011","058","222"]},
    {"nombre": "Gerardo Osvaldo Gonzalez", "zona": "AMBA", "tipo": "Fumigaciones", "tel": "-", "fijo": False, "sucursales": ["052","167","187"]},
    {"nombre": "Vasquez Marisel Vicenta", "zona": "NOA", "tipo": "Fumigaciones", "tel": "-", "fijo": False, "sucursales": ["126","139","193"]},
    {"nombre": "Lassna SRL", "zona": "AMBA", "tipo": "Fumigaciones", "tel": "-", "fijo": False, "sucursales": ["051","171"]},
    {"nombre": "Sindel Siscobio", "zona": "NOA", "tipo": "Fumigaciones", "tel": "-", "fijo": False, "sucursales": ["146","158"]},
    {"nombre": "Contreras Mauricio Sergio", "zona": "Cuyo", "tipo": "Fumigaciones", "tel": "-", "fijo": False, "sucursales": ["159","172"]},
    {"nombre": "Manggini Pablo y Ulises", "zona": "AMBA", "tipo": "Fumigaciones", "tel": "-", "fijo": False, "sucursales": ["043","204"]},
    {"nombre": "Municipalidad de Moreno", "zona": "AMBA", "tipo": "Fumigaciones", "tel": "-", "fijo": False, "sucursales": ["023","232"]},
    {"nombre": "Jorge Alejandro Gardel", "zona": "NOA", "tipo": "Fumigaciones", "tel": "-", "fijo": False, "sucursales": ["120","212"]},
    {"nombre": "Imhoff Fernando Alberto", "zona": "Litoral", "tipo": "Fumigaciones", "tel": "-", "fijo": False, "sucursales": ["114","226"]},
    {"nombre": "Felix Raul Millan", "zona": "Cuyo", "tipo": "Fumigaciones", "tel": "-", "fijo": False, "sucursales": ["145"]},
    {"nombre": "Nazareno Marchilli", "zona": "AMBA", "tipo": "Fumigaciones", "tel": "-", "fijo": False, "sucursales": ["116"]},
    {"nombre": "Comservar SRL", "zona": "Cuyo", "tipo": "Fumigaciones", "tel": "-", "fijo": False, "sucursales": ["207"]},
    {"nombre": "Rabincho SRL", "zona": "NEA", "tipo": "Fumigaciones", "tel": "-", "fijo": False, "sucursales": ["220"]},
    {"nombre": "Perez Bobadilla Nicolas", "zona": "NEA", "tipo": "Fumigaciones", "tel": "-", "fijo": False, "sucursales": ["224"]},
    {"nombre": "Marcelo Domingo Pedregal", "zona": "NOA", "tipo": "Fumigaciones", "tel": "-", "fijo": False, "sucursales": ["229"]},
    {"nombre": "ULT SRL", "zona": "NOA", "tipo": "Fumigaciones", "tel": "-", "fijo": False, "sucursales": ["235"]},
]

ZONAS = sorted(set(p["zona"] for p in PROVEEDORES))


# --- Helpers ---

def _seed_data_dir():
    """Al arrancar en Render, copiar datos iniciales del repo al disco persistente si no existen."""
    repo_data = Path(__file__).parent / "data"
    for fname in ["tickets.json", "stock.json", "stock_movimientos.json", "comprobantes.json", "habilitaciones.json"]:
        dest = DATA_DIR / fname
        src = repo_data / fname
        if not dest.exists() and src.exists():
            shutil.copy2(src, dest)

_seed_data_dir()


def load_tickets():
    if TICKETS_FILE.exists():
        return json.loads(TICKETS_FILE.read_text())
    return []


def save_tickets(tickets):
    TICKETS_FILE.write_text(json.dumps(tickets, indent=2, ensure_ascii=False))


def auto_priority(categoria, subcategoria):
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

    # By category
    if subcategoria == "Luminarias":
        return "Jonathan"
    if categoria == "Materiales" or subcategoria == "Solicitud de materiales":
        return "Jonathan"
    if subcategoria in ("Reparacion", "Sin funcionamiento", "Goteo", "Limpieza interna de equipo") and "Aire" in subcategoria:
        # AA in AMBA goes to CEYH
        if suc_num not in SUCS_CORDOBA and suc_num not in SUCS_NOA and suc_num not in SUCS_MENDOZA and suc_num not in SUCS_SANJUAN:
            return "CEYH"

    # By zone
    if suc_num in SUCS_CORDOBA:
        return "Gustavo Avellaneda"
    if suc_num in SUCS_NOA:
        return "Julio Fuga (JRF)"
    if suc_num in SUCS_MENDOZA:
        return "Ismael Allende (JRF)"
    if suc_num in SUCS_SANJUAN:
        return "Oscar San Juan"

    return ASIGNACION_DEFAULT


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


@app.route("/logout")
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
            if suc_num in s or suc_num.lstrip("0") in s:
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

    return render_template(
        "suc_panel.html",
        tickets=mis_tickets,
        prioridades=PRIORIDADES,
        mis_proveedores=mis_proveedores,
        notificaciones=notificaciones,
        mi_stock_insumos=mi_stock_insumos,
        mi_stock_manten=mi_stock_manten,
    )


@app.route("/mis-proveedores")
@suc_login_required
def suc_proveedores():
    suc_num = session["suc_nombre"].replace("Sucursal ", "").strip()
    mis_proveedores = []
    for p in PROVEEDORES:
        for s in p["sucursales"]:
            if suc_num in s or suc_num.lstrip("0") in s:
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
        ticket = {
            "id": tid,
            "sucursal": session.get("suc_nombre", request.form.get("sucursal", "")),
            "categoria": categoria,
            "subcategoria": subcategoria,
            "descripcion": request.form.get("descripcion", ""),
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
    ticket["actualizado"] = datetime.datetime.now().isoformat()

    # Handle next step
    siguiente_paso = request.form.get("siguiente_paso", "sucursal")
    pasos = {
        "personal_mantenimiento": ("En progreso", "Trabajo a realizar con personal de Mantenimiento Central"),
        "proveedor_abono": ("En progreso", "Coordinar con proveedor del abono mensual"),
        "proveedor_eventual": ("En progreso", "Coordinar con proveedor eventual"),
        "sucursal": ("Cerrado", "Trabajo a realizar con personal propio de sucursal"),
    }
    estado, paso_texto = pasos.get(siguiente_paso, ("Cerrado", ""))

    ticket["estado"] = estado
    ticket["siguiente_paso"] = siguiente_paso
    ticket["notas"].append({
        "autor": session.get("suc_nombre", "Sucursal"),
        "fecha": datetime.datetime.now().isoformat(),
        "texto": f"Siguiente paso: {paso_texto}",
    })

    # Si va a Personal de Mantenimiento Central, asignar al equipo y avisar al admin
    if siguiente_paso == "personal_mantenimiento":
        ticket["asignado_equipo"] = "Equipo Central"
        if not ticket.get("etapa_equipo"):
            ticket["etapa_equipo"] = "asignado"
        agregar_notif_admin(
            titulo=f"Equipo Central - Trabajo asignado #{ticket_id}",
            detalle=f"{ticket['sucursal']} confirmo recepcion. El equipo de Mantenimiento Central debe ejecutar el trabajo.",
            tipo="equipo_central",
            autor=session.get("suc_nombre", "Sucursal"),
            link=url_for("admin_ticket", ticket_id=ticket_id),
        )

    # Notify provider
    if "notificaciones_prov" not in ticket:
        ticket["notificaciones_prov"] = []
    notif_texto = f"{session.get('suc_nombre', 'Sucursal')} confirmo recepcion de materiales."
    if siguiente_paso in ("proveedor_abono", "proveedor_eventual"):
        notif_texto += " Se requiere coordinar visita para ejecutar el trabajo."
    ticket["notificaciones_prov"].append({
        "fecha": datetime.datetime.now().isoformat(),
        "texto": f"{session.get('suc_nombre', 'Sucursal')} confirmo recepcion de materiales. Ya cuenta con los materiales.",
    })

    # Si la sucursal eligio "Proveedor del abono", crear ticket vinculado
    if siguiente_paso == "proveedor_abono":
        suc_num = ticket["sucursal"].replace("Sucursal ", "").strip()
        prov_abono = get_proveedor_abono_sucursal(suc_num)
        if prov_abono:
            now_iso = datetime.datetime.now().isoformat()
            new_id = next_ticket_id(tickets)
            descripcion_nueva = (ticket.get("descripcion", "") or "").strip()
            descripcion_nueva += "\n\nRequiere trabajo con materiales recibidos"
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
                "notas": [{
                    "autor": "Sistema",
                    "fecha": now_iso,
                    "texto": f"Ticket generado automaticamente desde pedido de materiales #{ticket['id']}",
                }],
            }
            tickets.append(nuevo)
            ticket["trabajo_proveedor_ticket_id"] = new_id
            ticket["notas"].append({
                "autor": "Sistema",
                "fecha": now_iso,
                "texto": f"Se creo ticket #{new_id} asignado a {prov_abono} para ejecutar el trabajo",
            })

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


@app.route("/admin/logout")
def admin_logout():
    session.clear()
    return redirect(url_for("admin_login"))


@app.route("/admin")
@login_required
def admin_panel():
    # Jonathan (tecnico) va directo a sus pedidos
    if session.get("rol") == "tecnico":
        return redirect(url_for("admin_pedidos"))
    tickets = load_tickets()
    filtro_estado = request.args.get("estado", "")
    filtro_suc = request.args.get("sucursal", "")
    filtro_prioridad = request.args.get("prioridad", "")

    filtered = tickets
    if filtro_estado:
        filtered = [t for t in filtered if t["estado"] == filtro_estado]
    if filtro_suc:
        filtered = [t for t in filtered if t["sucursal"] == filtro_suc]
    if filtro_prioridad:
        filtered = [t for t in filtered if t["prioridad"] == int(filtro_prioridad)]

    filtered.sort(key=lambda t: t["creado"], reverse=True)

    stats = {
        "total": len(tickets),
        "nuevos": sum(1 for t in tickets if t["estado"] == "Nuevo"),
        "abiertos": sum(1 for t in tickets if t["estado"] == "Abierto"),
        "en_progreso": sum(1 for t in tickets if t["estado"] == "En progreso"),
        "pendientes": sum(1 for t in tickets if t["estado"] == "Pendiente"),
        "resueltos": sum(1 for t in tickets if t["estado"] == "Resuelto"),
    }

    # Chart data
    from collections import Counter
    prioridad_counts = Counter(PRIORIDADES.get(t["prioridad"], "?") for t in tickets)
    categoria_counts = Counter(t.get("categoria", "Otro") for t in tickets)
    asignado_counts = Counter(t.get("asignado", "Sin asignar") for t in tickets)

    # My work counts
    user_nombre = session.get("nombre", "")
    mis_esperando = [t for t in tickets if t.get("asignado") == user_nombre and t["estado"] in ("Nuevo", "Abierto")]
    mis_asignados = [t for t in tickets if t.get("asignado") == user_nombre and t["estado"] not in ("Resuelto", "Cerrado")]
    sin_asignar = [t for t in tickets if not t.get("asignado") or t.get("asignado") == ""]

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
            except:
                pass
    alertas.sort(key=lambda t: t.get("dias", 0), reverse=True)

    vista = request.args.get("vista", "dashboard")

    # Notificaciones admin (stock / facturas cargadas)
    notif_data = load_notif_admin()
    notif_admin = [n for n in notif_data.get("notificaciones", []) if not n.get("leida")][:10]

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
        vista=vista,
        alertas=alertas,
        notif_admin=notif_admin,
    )


@app.route("/admin/ticket/<int:ticket_id>", methods=["GET", "POST"])
@login_required
def admin_ticket(ticket_id):
    tickets = load_tickets()
    ticket = next((t for t in tickets if t["id"] == ticket_id), None)
    if not ticket:
        return "Ticket no encontrado", 404

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
            if ticket["estado"] in ("Nuevo", "Abierto"):
                ticket["estado"] = "Pendiente"
            ticket["actualizado"] = datetime.datetime.now().isoformat()
            save_tickets(tickets)
            flash("Respuesta enviada a la sucursal")
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

    return render_template(
        "admin_ticket.html",
        ticket=ticket,
        estados=ESTADOS,
        prioridades=PRIORIDADES,
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
        except:
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


@app.route("/proveedor/logout")
def prov_logout():
    session.pop("prov_user", None)
    session.pop("prov_nombre", None)
    return redirect(url_for("prov_login"))


@app.route("/proveedor")
@prov_login_required
def prov_panel():
    tickets = load_tickets()
    prov_nombre = session.get("prov_nombre", "")
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

    return render_template(
        "prov_panel.html",
        pendientes=pendientes,
        trabajos_materiales=trabajos_materiales,
        resueltos=resueltos,
        prioridades=PRIORIDADES,
        notificaciones=notif_prov,
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

        ticket["actualizado"] = datetime.datetime.now().isoformat()
        save_tickets(tickets)
        flash("Actualizado")
        return redirect(url_for("prov_ticket", ticket_id=ticket_id))

    return render_template("prov_ticket.html", ticket=ticket, prioridades=PRIORIDADES)


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


@app.route("/compras/logout")
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
        if t.get("siguiente_paso") == "personal_mantenimiento"
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


@app.route("/equipo/logout")
def equipo_logout():
    session.pop("equipo_user", None)
    session.pop("equipo_nombre", None)
    return redirect(url_for("equipo_login"))


@app.route("/equipo")
@equipo_login_required
def equipo_panel():
    tickets = load_tickets()
    mis = _tickets_equipo(tickets)

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


@app.route("/uploads/trabajos/<filename>")
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

    # Proveedores que cubren esta sucursal
    mis_proveedores = []
    for p in PROVEEDORES:
        for s in p["sucursales"]:
            if suc_num in s or suc_num.lstrip("0") in s:
                mis_proveedores.append(p)
                break

    # Inventario from Google Sheets
    inventario = {}
    try:
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "google_calendar"))
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
    except:
        pass

    return render_template(
        "admin_sucursal.html",
        suc_num=suc_num,
        suc_name=suc_name,
        info=info,
        activos=activos,
        cerrados=cerrados,
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
            except:
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

    # Send email via Gmail API
    try:
        from gauth import gmail as get_gmail
        import base64
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText

        service = get_gmail()
        msg = MIMEMultipart("alternative")
        msg["To"] = "agustintomasbrahim@gmail.com"
        msg["Subject"] = f"Tecman - Reporte Semanal {now.strftime('%d/%m/%Y')}"
        msg.attach(MIMEText(html, "html"))
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        service.users().messages().send(userId="me", body={"raw": raw}).execute()
        flash("Reporte enviado a agustintomasbrahim@gmail.com")
    except Exception as e:
        flash(f"Error al enviar: {str(e)}")

    return redirect(url_for("admin_panel", vista="dashboard"))


# --- Routes: Buscador ---

@app.route("/admin/buscar")
@admin_required
def admin_buscar():
    q = request.args.get("q", "").strip().lower()
    tickets = load_tickets()
    resultados = []
    if q:
        for t in tickets:
            if (q in str(t.get("id", "")) or
                q in t.get("sucursal", "").lower() or
                q in t.get("descripcion", "").lower() or
                q in t.get("subcategoria", "").lower() or
                q in t.get("categoria", "").lower() or
                q in t.get("asignado", "").lower() or
                q in t.get("observaciones", "").lower()):
                resultados.append(t)
    return render_template("admin_buscar.html", q=q, resultados=resultados, prioridades=PRIORIDADES)


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


@app.route("/syh/logout")
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
    )


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
            fname = f"syh_{suc_num}_{uuid.uuid4().hex[:8]}{ext}"
            f.save(str(UPLOADS_DIR / fname))
            if "documentos" not in syh_data[suc_num]:
                syh_data[suc_num]["documentos"] = []
            syh_data[suc_num]["documentos"] = estado.get("documentos", []) + [{"nombre": f.filename, "archivo": fname, "fecha": datetime.datetime.now().isoformat()}]
        else:
            syh_data[suc_num]["documentos"] = estado.get("documentos", [])
        save_syh(syh_data)
        flash("Sucursal actualizada")
        return redirect(url_for("syh_panel"))

    return render_template(
        "syh_edit.html",
        suc_num=suc_num,
        info=info,
        estado=estado,
        syh_estados=SYH_ESTADOS,
    )


# --- Routes: S&H Admin (duplicate for admin access) ---

@app.route("/admin/syh")
@admin_required
def admin_syh():
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

    # Stats
    total = len(sucursales_syh)
    habilitadas = sum(1 for s in sucursales_syh if s["habilitacion"] == "Vigente")
    bomberos_ok = sum(1 for s in sucursales_syh if s["bomberos"] == "Aprobado")
    sin_datos = sum(1 for s in sucursales_syh if s["habilitacion"] == "Sin datos")

    return render_template(
        "admin_syh.html",
        sucursales=sucursales_syh,
        total=total,
        habilitadas=habilitadas,
        bomberos_ok=bomberos_ok,
        sin_datos=sin_datos,
        syh_estados=SYH_ESTADOS,
    )


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
            "bomberos": request.form.get("bomberos", ""),
            "matafuegos": request.form.get("matafuegos", ""),
            "matafuegos_cantidad": request.form.get("matafuegos_cantidad", ""),
            "matafuegos_vencimiento": request.form.get("matafuegos_vencimiento", ""),
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
            fname = f"syh_{suc_num}_{uuid.uuid4().hex[:8]}{ext}"
            f.save(str(UPLOADS_DIR / fname))
            if "documentos" not in syh_data[suc_num]:
                syh_data[suc_num]["documentos"] = []
            syh_data[suc_num]["documentos"] = estado.get("documentos", []) + [{"nombre": f.filename, "archivo": fname, "fecha": datetime.datetime.now().isoformat()}]
        else:
            syh_data[suc_num]["documentos"] = estado.get("documentos", [])

        save_syh(syh_data)
        flash("Sucursal actualizada")
        return redirect(url_for("admin_syh"))

    return render_template(
        "admin_syh_edit.html",
        suc_num=suc_num,
        info=info,
        estado=estado,
        syh_estados=SYH_ESTADOS,
    )


# --- Routes: Jonathan - Pedidos de materiales ---

@app.route("/admin/pedidos")
@login_required
def admin_pedidos():
    tickets = load_tickets()
    # Filter material tickets assigned to Jonathan
    pedidos = [t for t in tickets if (t.get("categoria") in ("Materiales", "Solicitud de materiales") or t.get("tipo") == "materiales") and t["estado"] not in ("Cerrado",)]
    pendientes = [t for t in pedidos if t["estado"] in ("Nuevo", "Abierto")]
    en_proceso = [t for t in pedidos if t["estado"] in ("En progreso", "Pendiente")]
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
                "autor": session.get("nombre", "Jonathan"),
                "fecha": datetime.datetime.now().isoformat(),
                "texto": f"Cuento con material. Envio: {metodo_envio}",
            })

        elif accion == "solicitar_compras":
            detalle = request.form.get("detalle_compras", "")
            ticket["estado"] = "Pendiente"
            ticket["detalle_compras"] = detalle  # internal only
            ticket["notas"].append({
                "autor": session.get("nombre", "Jonathan"),
                "fecha": datetime.datetime.now().isoformat(),
                "texto": "Pedido realizado a compras",
            })

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
                # Usar precio del ultimo ingreso historico (fecha de compra)
                # para respetar el valor unitario vigente al momento de la compra
                precio_unit = _get_precio_historico(item_key) or get_central_precio(stock_data, item_key)
                disponible = get_central_qty(stock_data, item_key)
                nuevo = max(0, disponible - cantidad_env)
                if nuevo == 0 and item_key in stock_data.get("central", {}):
                    # Preservar precio en item con cantidad 0
                    stock_data["central"][item_key]["cantidad"] = 0
                elif item_key in stock_data.get("central", {}):
                    stock_data["central"][item_key]["cantidad"] = nuevo
                save_stock(stock_data)

                imputacion_monto = round(cantidad_env * precio_unit, 2)
                ticket["imputacion_item"] = item_key
                ticket["imputacion_cantidad"] = cantidad_env
                ticket["imputacion_precio_unitario"] = precio_unit
                ticket["imputacion_monto"] = imputacion_monto
                ticket["imputacion_fecha"] = datetime.datetime.now().isoformat()

                descuento_txt = f" | Stock descontado: '{item_key}' -{cantidad_env} (quedaron {nuevo})"
                if precio_unit > 0:
                    imputacion_txt = f" | Imputado a {ticket.get('sucursal', '')}: ${imputacion_monto:,.2f} ({cantidad_env} x ${precio_unit:,.2f})"
                else:
                    imputacion_txt = " | Sin precio unitario cargado (imputacion $0)"

                nota_mov = f"Enviado por ticket #{ticket.get('id')}"
                if metodo:
                    nota_mov += f" ({metodo})"
                registrar_movimiento(
                    item=item_key,
                    tipo="egreso",
                    cantidad=cantidad_env,
                    sucursal=ticket.get("sucursal", ""),
                    ticket_id=ticket.get("id"),
                    nota=nota_mov,
                    monto_imputado=imputacion_monto,
                    precio_unitario=precio_unit,
                )
            ticket["notas"].append({
                "autor": session.get("nombre", "Jonathan"),
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

    # Items del pedido.
    cat = ticket.get("categoria_mat", "") or ""
    subitem = ticket.get("subitem_mat", "") or ""
    try:
        cantidad = int(ticket.get("cantidad_mat") or 1)
    except (TypeError, ValueError):
        cantidad = 1
    detalle = f"{cat} - {subitem}" if (cat and subitem) else (cat or subitem or ticket.get("subcategoria", ""))
    items = []
    if detalle:
        items.append({"cantidad": cantidad, "detalle": detalle})

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
                registrar_movimiento(
                    item=nombre,
                    tipo="ingreso",
                    cantidad=cant,
                    sucursal="Central Dabra",
                    nota=f"Ingreso por remito {numero} ({proveedor})",
                    precio_unitario=precio if precio > 0 else None,
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
        "id": uuid.uuid4().hex[:12],
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

    # Agrupar por sucursal
    por_suc = {}
    for t in imputados:
        suc = t.get("sucursal", "Sin sucursal")
        fecha_imp = (t.get("imputacion_fecha") or t.get("actualizado") or t.get("creado") or "")[:10]
        fila = {
            "ticket_id": t.get("id"),
            "item": t.get("imputacion_item", ""),
            "cantidad": t.get("imputacion_cantidad", 0),
            "precio_unitario": float(t.get("imputacion_precio_unitario", 0) or 0),
            "subtotal": float(t.get("imputacion_monto", 0) or 0),
            "fecha": fecha_imp,
        }
        grupo = por_suc.setdefault(suc, {"items": [], "total": 0.0, "cantidad_items": 0})
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
        writer.writerow(["Sucursal", "Item", "Cantidad", "Precio Unit.", "Subtotal", "Fecha", "Ticket#"])
        for suc_nom, grupo in reporte:
            for fila in grupo["items"]:
                writer.writerow([
                    suc_nom,
                    fila["item"],
                    fila["cantidad"],
                    f"{fila['precio_unitario']:.2f}",
                    f"{fila['subtotal']:.2f}",
                    fila["fecha"],
                    fila["ticket_id"],
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
def serve_habilitacion(filename):
    return send_from_directory(str(HABILITACIONES_DIR), filename)


# --- API ---

@app.route("/api/categorias")
def api_categorias():
    cat = request.args.get("categoria", "")
    return jsonify(CATEGORIAS.get(cat, []))


@app.route("/guia-luminaria")
def guia_luminaria():
    return render_template("guia_luminaria.html")


@app.route("/static/uploads/guias/<filename>")
def serve_guia(filename):
    return send_from_directory(str(GUIAS_DIR), filename)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5050, debug=True)
