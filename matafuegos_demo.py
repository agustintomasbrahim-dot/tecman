"""Portal DEMO aislado para proveedores de matafuegos.

Este módulo no importa ni modifica tickets, matafuegos, usuarios, alertas o
notificaciones operativas. Todo el estado vive en un JSON y un directorio de
adjuntos exclusivos dentro de DATA_DIR.
"""

from __future__ import annotations

import copy
import datetime as dt
import json
import os
import re
import secrets
import uuid
from decimal import Decimal, InvalidOperation
from functools import wraps
from pathlib import Path

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)


demo_bp = Blueprint("matafuegos_demo", __name__)

DEMO_STATES = ("Pendiente", "Programado", "Realizado", "Validado")
EXTINGUISHER_TYPES = ("ABC", "CO2", "Agua", "Otro")
PHYSICAL_STATES = ("Bueno", "Regular", "Malo", "Fuera de servicio")
WORK_TYPES = ("recargado", "reparado", "reemplazado", "rechazado", "otro")
CAPACITY_PRESETS = ("1", "2.5", "5", "10", "25")
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
DOCUMENT_EXTENSIONS = IMAGE_EXTENSIONS | {".pdf"}
ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,80}$")


class DemoValidationError(ValueError):
    pass


def _data_file() -> Path:
    return Path(current_app.config["MATAFUEGOS_DEMO_DATA_FILE"])


def _uploads_dir() -> Path:
    path = Path(current_app.config["MATAFUEGOS_DEMO_UPLOADS_DIR"])
    path.mkdir(parents=True, exist_ok=True)
    return path


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _today() -> dt.date:
    return dt.date.today()


def _atomic_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def _history(actor: str, action: str, detail: str = "") -> dict:
    return {"fecha": _now(), "actor": actor, "accion": action, "detalle": detail}


def _seed_data() -> dict:
    today = _today()
    tomorrow = today + dt.timedelta(days=1)
    next_month = today + dt.timedelta(days=30)
    next_year = today + dt.timedelta(days=365)

    def item(item_id: str, location: str, serial: str, capacity: str = "5", extinguisher_type: str = "ABC") -> dict:
        return {
            "id": item_id,
            "activo": True,
            "tipo": extinguisher_type,
            "capacidad_kg": capacity,
            "cantidad_unidades": 1,
            "ubicacion": location,
            "identificacion": serial,
            "encontrado": "si",
            "estado_fisico": "Bueno",
            "trabajo_realizado": "recargado",
            "fecha_recarga": today.isoformat(),
            "proximo_vencimiento": next_year.isoformat(),
            "observacion": "Equipo ficticio para demostración.",
            "fotos_antes": [],
            "fotos_despues": [],
            "creado": _now(),
            "actualizado": _now(),
        }

    return {
        "schema_version": 1,
        "demo": True,
        "ordenes": [
            {
                "id": "DEMO-001",
                "demo": True,
                "sucursal": "Sucursal Demo Centro",
                "direccion": "Avenida Ficticia 123, Ciudad Demo",
                "contacto": "Contacto Demo Centro",
                "telefono": "+54 11 0000-0001",
                "estado": "Pendiente",
                "fecha_programada": "",
                "observacion_devolucion": "",
                "matafuegos": [],
                "documentos": {},
                "historial": [_history("Sistema DEMO", "Orden creada", "Datos completamente ficticios")],
            },
            {
                "id": "DEMO-002",
                "demo": True,
                "sucursal": "Sucursal Demo Norte",
                "direccion": "Calle Inventada 456, Barrio Demo",
                "contacto": "Contacto Demo Norte",
                "telefono": "+54 11 0000-0002",
                "estado": "Programado",
                "fecha_programada": tomorrow.isoformat(),
                "observacion_devolucion": "",
                "matafuegos": [item("EXT-DEMO-002-A", "Salón principal", "SERIE-DEMO-002")],
                "documentos": {},
                "historial": [
                    _history("Sistema DEMO", "Orden creada", "Datos completamente ficticios"),
                    _history("Demo Matafuegos", "Programado", tomorrow.isoformat()),
                ],
            },
            {
                "id": "DEMO-003",
                "demo": True,
                "sucursal": "Sucursal Demo Sur",
                "direccion": "Ruta Simulada 789, Parque Demo",
                "contacto": "Contacto Demo Sur",
                "telefono": "+54 11 0000-0003",
                "estado": "Realizado",
                "fecha_programada": today.isoformat(),
                "observacion_devolucion": "",
                "matafuegos": [item("EXT-DEMO-003-A", "Depósito ficticio", "SERIE-DEMO-003", "2.5", "CO2")],
                "documentos": {
                    "remito": {"nombre_original": "remito_demo_precargado.pdf", "archivo": "", "demo_precargado": True},
                    "certificado": {"nombre_original": "certificado_demo_precargado.pdf", "archivo": "", "demo_precargado": True},
                },
                "historial": [
                    _history("Sistema DEMO", "Orden creada", "Datos completamente ficticios"),
                    _history("Demo Matafuegos", "Programado", today.isoformat()),
                    _history("Demo Matafuegos", "Realizado", "Documentación DEMO precargada"),
                ],
            },
        ],
    }


def load_demo_data() -> dict:
    path = _data_file()
    if not path.exists() or path.stat().st_size == 0:
        data = _seed_data()
        _atomic_write(path, data)
        return data
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("El dataset DEMO no se pudo leer; no fue sobrescrito.") from exc
    if not isinstance(data, dict):
        raise RuntimeError("El dataset DEMO tiene un formato inválido; no fue sobrescrito.")
    if not data.get("ordenes"):
        data = _seed_data()
        _atomic_write(path, data)
    return data


def save_demo_data(data: dict) -> None:
    _atomic_write(_data_file(), data)


def _find_order(data: dict, order_id: str) -> dict | None:
    if not ID_RE.fullmatch(order_id or ""):
        return None
    return next((order for order in data.get("ordenes", []) if order.get("id") == order_id), None)


def _session_valid() -> bool:
    validator = current_app.config.get("TECMAN_SESSION_AUTH_VALIDATOR")
    return bool(validator() if validator else True)


def demo_required(view):
    @wraps(view)
    def decorated(*args, **kwargs):
        if "prov_user" not in session:
            return redirect(url_for("prov_login"))
        if not _session_valid():
            session.clear()
            return redirect(url_for("prov_login"))
        if session.get("prov_tipo_cuenta") != "matafuegos_demo" or session.get("prov_user") != "matafuegos_demo":
            return render_template("error.html", mensaje="Acceso restringido al portal DEMO de matafuegos."), 403
        return view(*args, **kwargs)

    return decorated


def demo_admin_required(view):
    @wraps(view)
    def decorated(*args, **kwargs):
        if "user" not in session or not _session_valid():
            session.clear()
            return redirect(url_for("admin_login"))
        if session.get("rol") != "admin":
            return render_template("error.html", mensaje="Acceso restringido. Solo administradores."), 403
        if session.get("auth_provider") == "entra" and session.get("entra_role") != "admin":
            session.clear()
            return redirect(url_for("admin_login"))
        return view(*args, **kwargs)

    return decorated


def _csrf_ok() -> bool:
    expected = session.get("_csrf_token", "")
    submitted = request.form.get("_csrf_token", "")
    return bool(expected and submitted and secrets.compare_digest(expected, submitted))


def _require_csrf():
    if not _csrf_ok():
        return render_template("error.html", mensaje="Solicitud inválida o vencida."), 400
    return None


def _clean_text(value, label: str, *, required: bool = False, max_length: int = 300) -> str:
    text = " ".join(str(value or "").strip().split())
    if required and not text:
        raise DemoValidationError(f"{label} es obligatorio.")
    if len(text) > max_length or any(ord(char) < 32 for char in text):
        raise DemoValidationError(f"{label} es inválido o demasiado largo.")
    if text.startswith(("=", "+", "@")):
        raise DemoValidationError(f"{label} no puede comenzar con un indicador de fórmula.")
    return text


def _parse_iso_date(value, label: str, *, required: bool = True) -> str:
    raw = str(value or "").strip()
    if not raw and not required:
        return ""
    try:
        return dt.date.fromisoformat(raw).isoformat()
    except (TypeError, ValueError) as exc:
        raise DemoValidationError(f"{label} debe ser una fecha válida.") from exc


def _parse_capacity(value) -> str:
    raw = str(value or "").strip().replace(",", ".")
    try:
        parsed = Decimal(raw)
    except (InvalidOperation, ValueError) as exc:
        raise DemoValidationError("La capacidad debe ser un número decimal válido.") from exc
    if not parsed.is_finite() or parsed <= 0 or parsed > Decimal("1000"):
        raise DemoValidationError("La capacidad debe ser mayor que cero y no superar 1000 kg.")
    if parsed.as_tuple().exponent < -2:
        raise DemoValidationError("La capacidad admite como máximo dos decimales.")
    normalized = format(parsed.normalize(), "f")
    return normalized


def _parse_quantity(value) -> int:
    raw = str(value or "").strip()
    if not raw.isdigit():
        raise DemoValidationError("La cantidad de unidades debe ser un entero mayor que cero.")
    quantity = int(raw)
    if quantity <= 0 or quantity > 1000:
        raise DemoValidationError("La cantidad de unidades debe estar entre 1 y 1000.")
    return quantity


def _item_from_form(existing: dict | None = None) -> dict:
    extinguisher_type = _clean_text(request.form.get("tipo"), "Tipo", required=True, max_length=20)
    if extinguisher_type not in EXTINGUISHER_TYPES:
        raise DemoValidationError("El tipo de matafuego no es válido.")
    physical_state = _clean_text(request.form.get("estado_fisico"), "Estado físico", required=True, max_length=40)
    if physical_state not in PHYSICAL_STATES:
        raise DemoValidationError("El estado físico no es válido.")
    work = _clean_text(request.form.get("trabajo_realizado"), "Trabajo realizado", required=True, max_length=30)
    if work not in WORK_TYPES:
        raise DemoValidationError("El trabajo realizado no es válido.")
    found = _clean_text(request.form.get("encontrado"), "Encontrado", required=True, max_length=3)
    if found not in ("si", "no"):
        raise DemoValidationError("Indicá si el matafuego fue encontrado.")
    recharge = _parse_iso_date(request.form.get("fecha_recarga"), "Fecha de recarga")
    expiry = _parse_iso_date(request.form.get("proximo_vencimiento"), "Próximo vencimiento")
    if expiry <= recharge:
        raise DemoValidationError("El próximo vencimiento debe ser posterior a la fecha de recarga.")

    item = copy.deepcopy(existing or {})
    item.update(
        {
            "id": item.get("id") or f"EXT-{uuid.uuid4().hex[:12].upper()}",
            "activo": item.get("activo", True),
            "tipo": extinguisher_type,
            "capacidad_kg": _parse_capacity(request.form.get("capacidad_kg")),
            "cantidad_unidades": _parse_quantity(request.form.get("cantidad_unidades")),
            "ubicacion": _clean_text(request.form.get("ubicacion"), "Ubicación", required=True, max_length=160),
            "identificacion": _clean_text(request.form.get("identificacion"), "Número de serie/identificación", required=True, max_length=120),
            "encontrado": found,
            "estado_fisico": physical_state,
            "trabajo_realizado": work,
            "fecha_recarga": recharge,
            "proximo_vencimiento": expiry,
            "observacion": _clean_text(request.form.get("observacion"), "Observación", max_length=1000),
            "fotos_antes": list(item.get("fotos_antes") or []),
            "fotos_despues": list(item.get("fotos_despues") or []),
            "actualizado": _now(),
        }
    )
    item.setdefault("creado", _now())
    return item


def _signature_ok(extension: str, content: bytes) -> bool:
    if extension == ".pdf":
        return content.startswith(b"%PDF-")
    if extension in (".jpg", ".jpeg"):
        return content.startswith(b"\xff\xd8\xff")
    if extension == ".png":
        return content.startswith(b"\x89PNG\r\n\x1a\n")
    if extension == ".webp":
        return len(content) >= 12 and content.startswith(b"RIFF") and content[8:12] == b"WEBP"
    return False


def _prepare_upload(storage, label: str, allowed_extensions: set[str]) -> dict | None:
    if not storage or not storage.filename:
        return None
    original = Path(storage.filename).name
    if original != storage.filename or original in (".", ".."):
        raise DemoValidationError(f"El nombre de archivo de {label} es inválido.")
    extension = Path(original).suffix.lower()
    if extension not in allowed_extensions:
        raise DemoValidationError(f"El formato de {label} no está permitido.")
    max_bytes = int(current_app.config.get("MAX_CONTENT_LENGTH") or 60 * 1024 * 1024)
    content = storage.stream.read(max_bytes + 1)
    if not content:
        raise DemoValidationError(f"El archivo de {label} está vacío.")
    if len(content) > max_bytes:
        raise DemoValidationError(f"El archivo de {label} supera el límite permitido.")
    if not _signature_ok(extension, content):
        raise DemoValidationError(f"El contenido de {label} no coincide con su extensión.")
    return {
        "nombre_original": _clean_text(original, f"Nombre de {label}", required=True, max_length=180),
        "archivo": f"demo_{uuid.uuid4().hex}{extension}",
        "contenido": content,
        "tamano": len(content),
    }


def _persist_uploads(prepared: list[dict]) -> list[Path]:
    created = []
    try:
        for upload in prepared:
            destination = _uploads_dir() / upload["archivo"]
            temp = destination.with_name(f".{destination.name}.tmp")
            temp.write_bytes(upload["contenido"])
            os.replace(temp, destination)
            created.append(destination)
        return created
    except Exception:
        for path in created:
            if path.exists():
                path.unlink()
        raise


def _upload_metadata(upload: dict) -> dict:
    return {key: upload[key] for key in ("nombre_original", "archivo", "tamano")}


def _assert_editable(order: dict) -> None:
    if order.get("estado") not in ("Pendiente", "Programado"):
        raise DemoValidationError("La orden debe estar Pendiente o Programada para editar el relevamiento.")


def _active_items(order: dict) -> list[dict]:
    return [item for item in order.get("matafuegos", []) if item.get("activo", True)]


def _validate_completion(order: dict) -> None:
    if order.get("estado") != "Programado":
        raise DemoValidationError("Sólo una orden Programada puede pasar a Realizado.")
    if not _active_items(order):
        raise DemoValidationError("Debe haber al menos un matafuego activo.")
    for item in _active_items(order):
        required = (
            "tipo",
            "capacidad_kg",
            "cantidad_unidades",
            "ubicacion",
            "identificacion",
            "encontrado",
            "estado_fisico",
            "trabajo_realizado",
            "fecha_recarga",
            "proximo_vencimiento",
        )
        if any(item.get(field) in (None, "", 0) for field in required):
            raise DemoValidationError("Todos los matafuegos activos deben tener sus datos mínimos completos.")
        _parse_capacity(item.get("capacidad_kg"))
        _parse_quantity(item.get("cantidad_unidades"))
        recharge = _parse_iso_date(item.get("fecha_recarga"), "Fecha de recarga")
        expiry = _parse_iso_date(item.get("proximo_vencimiento"), "Próximo vencimiento")
        if expiry <= recharge:
            raise DemoValidationError("Cada vencimiento debe ser posterior a su fecha de recarga.")


def _render_detail(order: dict, *, is_admin: bool):
    return render_template(
        "matafuegos_demo_detalle.html",
        orden=order,
        is_admin=is_admin,
        estados=DEMO_STATES,
        tipos=EXTINGUISHER_TYPES,
        estados_fisicos=PHYSICAL_STATES,
        trabajos=WORK_TYPES,
        capacidades=CAPACITY_PRESETS,
        hoy=_today().isoformat(),
    )


@demo_bp.get("/proveedor/matafuegos-demo")
@demo_required
def panel():
    data = load_demo_data()
    state_filter = request.args.get("estado", "").strip()
    if state_filter and state_filter not in DEMO_STATES:
        state_filter = ""
    orders = data.get("ordenes", [])
    counts = {state: sum(1 for order in orders if order.get("estado") == state) for state in DEMO_STATES}
    filtered = [order for order in orders if not state_filter or order.get("estado") == state_filter]
    return render_template(
        "matafuegos_demo_panel.html",
        ordenes=filtered,
        conteos=counts,
        estados=DEMO_STATES,
        filtro_estado=state_filter,
        is_admin=False,
    )


@demo_bp.get("/proveedor/matafuegos-demo/orden/<order_id>")
@demo_required
def order_detail(order_id):
    order = _find_order(load_demo_data(), order_id)
    if not order:
        return render_template("error.html", mensaje="Orden DEMO no encontrada."), 404
    return _render_detail(order, is_admin=False)


@demo_bp.post("/proveedor/matafuegos-demo/orden/<order_id>/programar")
@demo_required
def schedule_order(order_id):
    invalid = _require_csrf()
    if invalid:
        return invalid
    data = load_demo_data()
    order = _find_order(data, order_id)
    if not order:
        return render_template("error.html", mensaje="Orden DEMO no encontrada."), 404
    try:
        if order.get("estado") != "Pendiente":
            raise DemoValidationError("Sólo una orden Pendiente puede programarse.")
        scheduled = _parse_iso_date(request.form.get("fecha_programada"), "Fecha programada")
        if scheduled < _today().isoformat():
            raise DemoValidationError("La fecha programada no puede estar en el pasado.")
        order["fecha_programada"] = scheduled
        order["estado"] = "Programado"
        order["observacion_devolucion"] = ""
        order.setdefault("historial", []).append(_history(session.get("prov_nombre", "Demo Matafuegos"), "Programado", scheduled))
        save_demo_data(data)
        flash("Orden DEMO programada.")
    except DemoValidationError as exc:
        flash(str(exc))
    return redirect(url_for("matafuegos_demo.order_detail", order_id=order_id))


@demo_bp.post("/proveedor/matafuegos-demo/orden/<order_id>/matafuegos")
@demo_required
def add_item(order_id):
    invalid = _require_csrf()
    if invalid:
        return invalid
    data = load_demo_data()
    order = _find_order(data, order_id)
    if not order:
        return render_template("error.html", mensaje="Orden DEMO no encontrada."), 404
    created_files: list[Path] = []
    try:
        _assert_editable(order)
        item = _item_from_form()
        before = _prepare_upload(request.files.get("foto_antes"), "foto antes", IMAGE_EXTENSIONS)
        after = _prepare_upload(request.files.get("foto_despues"), "foto después", IMAGE_EXTENSIONS)
        prepared = [upload for upload in (before, after) if upload]
        created_files = _persist_uploads(prepared)
        if before:
            item["fotos_antes"].append(_upload_metadata(before))
        if after:
            item["fotos_despues"].append(_upload_metadata(after))
        order.setdefault("matafuegos", []).append(item)
        order.setdefault("historial", []).append(_history(session.get("prov_nombre", "Demo Matafuegos"), "Matafuego agregado", item["identificacion"]))
        save_demo_data(data)
        flash("Matafuego agregado al relevamiento DEMO.")
    except DemoValidationError as exc:
        for path in created_files:
            if path.exists():
                path.unlink()
        flash(str(exc))
    except Exception:
        for path in created_files:
            if path.exists():
                path.unlink()
        raise
    return redirect(url_for("matafuegos_demo.order_detail", order_id=order_id))


@demo_bp.post("/proveedor/matafuegos-demo/orden/<order_id>/matafuegos/<item_id>")
@demo_required
def edit_item(order_id, item_id):
    invalid = _require_csrf()
    if invalid:
        return invalid
    data = load_demo_data()
    order = _find_order(data, order_id)
    if not order:
        return render_template("error.html", mensaje="Orden DEMO no encontrada."), 404
    item = next((entry for entry in order.get("matafuegos", []) if entry.get("id") == item_id), None)
    if not item or not ID_RE.fullmatch(item_id or ""):
        return render_template("error.html", mensaje="Matafuego DEMO no encontrado."), 404
    created_files: list[Path] = []
    try:
        _assert_editable(order)
        if not item.get("activo", True):
            raise DemoValidationError("Un matafuego anulado no puede editarse.")
        updated = _item_from_form(item)
        before = _prepare_upload(request.files.get("foto_antes"), "foto antes", IMAGE_EXTENSIONS)
        after = _prepare_upload(request.files.get("foto_despues"), "foto después", IMAGE_EXTENSIONS)
        prepared = [upload for upload in (before, after) if upload]
        created_files = _persist_uploads(prepared)
        if before:
            updated["fotos_antes"].append(_upload_metadata(before))
        if after:
            updated["fotos_despues"].append(_upload_metadata(after))
        item.clear()
        item.update(updated)
        order.setdefault("historial", []).append(_history(session.get("prov_nombre", "Demo Matafuegos"), "Matafuego editado", item["identificacion"]))
        save_demo_data(data)
        flash("Matafuego actualizado.")
    except DemoValidationError as exc:
        for path in created_files:
            if path.exists():
                path.unlink()
        flash(str(exc))
    except Exception:
        for path in created_files:
            if path.exists():
                path.unlink()
        raise
    return redirect(url_for("matafuegos_demo.order_detail", order_id=order_id))


@demo_bp.post("/proveedor/matafuegos-demo/orden/<order_id>/matafuegos/<item_id>/anular")
@demo_required
def void_item(order_id, item_id):
    invalid = _require_csrf()
    if invalid:
        return invalid
    data = load_demo_data()
    order = _find_order(data, order_id)
    if not order:
        return render_template("error.html", mensaje="Orden DEMO no encontrada."), 404
    item = next((entry for entry in order.get("matafuegos", []) if entry.get("id") == item_id), None)
    if not item or not ID_RE.fullmatch(item_id or ""):
        return render_template("error.html", mensaje="Matafuego DEMO no encontrado."), 404
    try:
        _assert_editable(order)
        reason = _clean_text(request.form.get("motivo"), "Motivo de anulación", required=True, max_length=500)
        if not item.get("activo", True):
            raise DemoValidationError("El matafuego ya está anulado.")
        item["activo"] = False
        item["anulado_motivo"] = reason
        item["anulado_fecha"] = _now()
        order.setdefault("historial", []).append(_history(session.get("prov_nombre", "Demo Matafuegos"), "Matafuego anulado", reason))
        save_demo_data(data)
        flash("Matafuego anulado sin eliminar su historial.")
    except DemoValidationError as exc:
        flash(str(exc))
    return redirect(url_for("matafuegos_demo.order_detail", order_id=order_id))


@demo_bp.post("/proveedor/matafuegos-demo/orden/<order_id>/finalizar")
@demo_required
def complete_order(order_id):
    invalid = _require_csrf()
    if invalid:
        return invalid
    data = load_demo_data()
    order = _find_order(data, order_id)
    if not order:
        return render_template("error.html", mensaje="Orden DEMO no encontrada."), 404
    created_files: list[Path] = []
    try:
        _validate_completion(order)
        remito = _prepare_upload(request.files.get("remito"), "remito", DOCUMENT_EXTENSIONS)
        certificate = _prepare_upload(request.files.get("certificado"), "certificado", DOCUMENT_EXTENSIONS)
        if not remito or not certificate:
            raise DemoValidationError("El remito y el certificado son obligatorios para finalizar.")
        created_files = _persist_uploads([remito, certificate])
        order["documentos"] = {
            "remito": _upload_metadata(remito),
            "certificado": _upload_metadata(certificate),
        }
        order["estado"] = "Realizado"
        order.setdefault("historial", []).append(_history(session.get("prov_nombre", "Demo Matafuegos"), "Realizado", "Remito y certificado adjuntos"))
        save_demo_data(data)
        flash("Trabajo DEMO marcado como Realizado y enviado a validación.")
    except DemoValidationError as exc:
        for path in created_files:
            if path.exists():
                path.unlink()
        flash(str(exc))
    except Exception:
        for path in created_files:
            if path.exists():
                path.unlink()
        raise
    return redirect(url_for("matafuegos_demo.order_detail", order_id=order_id))


@demo_bp.get("/admin/matafuegos-demo")
@demo_admin_required
def admin_panel():
    data = load_demo_data()
    orders = data.get("ordenes", [])
    counts = {state: sum(1 for order in orders if order.get("estado") == state) for state in DEMO_STATES}
    return render_template(
        "matafuegos_demo_panel.html",
        ordenes=orders,
        conteos=counts,
        estados=DEMO_STATES,
        filtro_estado="",
        is_admin=True,
    )


@demo_bp.get("/admin/matafuegos-demo/orden/<order_id>")
@demo_admin_required
def admin_order_detail(order_id):
    order = _find_order(load_demo_data(), order_id)
    if not order:
        return render_template("error.html", mensaje="Orden DEMO no encontrada."), 404
    return _render_detail(order, is_admin=True)


@demo_bp.post("/admin/matafuegos-demo/orden/<order_id>/validar")
@demo_admin_required
def validate_order(order_id):
    invalid = _require_csrf()
    if invalid:
        return invalid
    data = load_demo_data()
    order = _find_order(data, order_id)
    if not order:
        return render_template("error.html", mensaje="Orden DEMO no encontrada."), 404
    if order.get("estado") != "Realizado":
        flash("Sólo una orden Realizada puede validarse.")
    else:
        order["estado"] = "Validado"
        order.setdefault("historial", []).append(_history(session.get("nombre", "Admin"), "Validado", "Trabajo DEMO aprobado"))
        save_demo_data(data)
        flash("Trabajo DEMO validado.")
    return redirect(url_for("matafuegos_demo.admin_order_detail", order_id=order_id))


@demo_bp.post("/admin/matafuegos-demo/orden/<order_id>/devolver")
@demo_admin_required
def return_order(order_id):
    invalid = _require_csrf()
    if invalid:
        return invalid
    data = load_demo_data()
    order = _find_order(data, order_id)
    if not order:
        return render_template("error.html", mensaje="Orden DEMO no encontrada."), 404
    try:
        if order.get("estado") != "Realizado":
            raise DemoValidationError("Sólo una orden Realizada puede devolverse para corregir.")
        observation = _clean_text(request.form.get("observacion"), "Observación de devolución", required=True, max_length=1000)
        order["estado"] = "Pendiente"
        order["fecha_programada"] = ""
        order["observacion_devolucion"] = observation
        order.setdefault("historial", []).append(_history(session.get("nombre", "Admin"), "Devuelto para corregir", observation))
        save_demo_data(data)
        flash("Trabajo devuelto a Pendiente con observación.")
    except DemoValidationError as exc:
        flash(str(exc))
    return redirect(url_for("matafuegos_demo.admin_order_detail", order_id=order_id))


def _referenced_filename(data: dict, filename: str) -> bool:
    if Path(filename).name != filename or not re.fullmatch(r"demo_[a-f0-9]{32}\.(?:pdf|jpg|jpeg|png|webp)", filename):
        return False
    for order in data.get("ordenes", []):
        for document in (order.get("documentos") or {}).values():
            if document.get("archivo") == filename:
                return True
        for item in order.get("matafuegos", []):
            for key in ("fotos_antes", "fotos_despues"):
                if any(photo.get("archivo") == filename for photo in item.get(key, [])):
                    return True
    return False


@demo_bp.get("/matafuegos-demo/archivo/<filename>")
def serve_file(filename):
    is_demo = session.get("prov_user") == "matafuegos_demo" and session.get("prov_tipo_cuenta") == "matafuegos_demo"
    is_admin = session.get("user") and session.get("rol") == "admin"
    if not (is_demo or is_admin) or not _session_valid():
        return render_template("error.html", mensaje="Acceso restringido al archivo DEMO."), 403
    data = load_demo_data()
    if not _referenced_filename(data, filename):
        return render_template("error.html", mensaje="Archivo DEMO no encontrado."), 404
    return send_from_directory(str(_uploads_dir()), filename)
