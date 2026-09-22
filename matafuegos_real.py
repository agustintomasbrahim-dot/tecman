"""Portal operativo de matafuegos sobre tickets reales asignados.

El flujo vive bajo ``ticket['matafuegos_portal']`` y no cambia el estado
histórico/general del ticket. Los adjuntos usan un namespace por ticket y sólo
se sirven después de volver a autorizar el ticket para la sesión activa.
"""
from __future__ import annotations

import copy
import datetime as dt
import os
import re
import secrets
import uuid
from decimal import Decimal, InvalidOperation
from functools import wraps
from pathlib import Path

from flask import Blueprint, current_app, flash, redirect, render_template, request, send_from_directory, session, url_for

real_bp = Blueprint("matafuegos_real", __name__)

STATES = ("Pendiente", "Programado", "Realizado", "Validado")
EXTINGUISHER_TYPES = ("ABC", "CO2", "Agua", "HCFC-123", "Otro")
PHYSICAL_STATES = ("Bueno", "Regular", "Malo", "Fuera de servicio")
WORK_TYPES = ("recargado", "reparado", "reemplazado", "rechazado", "otro")
CAPACITY_PRESETS = ("1", "2.5", "5", "10", "25")
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
DOCUMENT_EXTENSIONS = IMAGE_EXTENSIONS | {".pdf"}
ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
REAL_UPLOAD_RE = re.compile(r"^[a-f0-9]{32}\.(?:pdf|jpg|jpeg|png|webp)$")


class ValidationError(ValueError):
    pass


def _load_tickets():
    return current_app.config["MATAFUEGOS_REAL_LOAD_TICKETS"]()


def _save_tickets(tickets):
    current_app.config["MATAFUEGOS_REAL_SAVE_TICKETS"](tickets)


def _provider_names():
    return current_app.config["MATAFUEGOS_REAL_PROVIDER_NAMES"]()


def _ticket_allowed(ticket):
    return bool(
        current_app.config["MATAFUEGOS_REAL_TICKET_VISIBLE"](ticket)
        and current_app.config["MATAFUEGOS_REAL_TICKET_ALLOWED"](ticket, _provider_names())
    )


def _refresh_session():
    callback = current_app.config.get("MATAFUEGOS_REAL_REFRESH_SESSION")
    return callback() if callback else session.get("prov_tipo_cuenta")


def _session_valid():
    validator = current_app.config.get("TECMAN_SESSION_AUTH_VALIDATOR")
    return bool(validator() if validator else True)


def real_required(view):
    @wraps(view)
    def decorated(*args, **kwargs):
        if "prov_user" not in session or not _session_valid():
            session.clear()
            return redirect(url_for("prov_login"))
        if _refresh_session() != "matafuegos":
            return render_template("error.html", mensaje="Acceso restringido al portal real de matafuegos."), 403
        return view(*args, **kwargs)
    return decorated


def admin_required(view):
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


def _csrf_required():
    expected = str(session.get("_csrf_token") or "")
    submitted = str(request.form.get("_csrf_token") or "")
    if not expected or not submitted or not secrets.compare_digest(expected, submitted):
        return render_template("error.html", mensaje="Solicitud inválida o vencida."), 400
    return None


def _now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _today():
    return dt.date.today()


def _clean(value, label, *, required=False, max_length=300):
    text = " ".join(str(value or "").strip().split())
    if required and not text:
        raise ValidationError(f"{label} es obligatorio.")
    if len(text) > max_length or any(ord(char) < 32 for char in text):
        raise ValidationError(f"{label} es inválido o demasiado largo.")
    if text.startswith(("=", "+", "@")):
        raise ValidationError(f"{label} no puede comenzar con un indicador de fórmula.")
    return text


def _date(value, label, *, required=True):
    raw = str(value or "").strip()
    if not raw and not required:
        return ""
    try:
        return dt.date.fromisoformat(raw).isoformat()
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{label} debe ser una fecha válida.") from exc


def _capacity(value):
    raw = str(value or "").strip().replace(",", ".")
    try:
        parsed = Decimal(raw)
    except (InvalidOperation, ValueError) as exc:
        raise ValidationError("La capacidad debe ser un número decimal válido.") from exc
    if not parsed.is_finite() or parsed <= 0 or parsed > Decimal("1000") or parsed.as_tuple().exponent < -2:
        raise ValidationError("La capacidad debe ser mayor que cero, no superar 1000 kg y admitir hasta dos decimales.")
    return format(parsed.normalize(), "f")


def _quantity(value):
    raw = str(value or "").strip()
    if not raw.isdigit() or not 1 <= int(raw) <= 1000:
        raise ValidationError("La cantidad de unidades debe estar entre 1 y 1000.")
    return int(raw)


def _history(actor, action, detail=""):
    return {"fecha": _now(), "actor": actor, "accion": action, "detalle": detail}


def _base_workflow(ticket):
    etapa = str(ticket.get("etapa_prov") or "").strip().lower()
    estado_ticket = str(ticket.get("estado") or "").strip().lower()
    if etapa in {"hecho", "trabajo_terminado"} or estado_ticket in {"resuelto", "cerrado"}:
        initial_state = "Realizado"
    elif ticket.get("fecha_visita") or etapa in {
        "planificado", "relevado", "en_progreso_prov", "esperando_materiales",
        "esperando_presupuesto", "en_camino", "trabajo_iniciado", "continua_manana",
    }:
        initial_state = "Programado"
    else:
        initial_state = "Pendiente"
    return {
        "schema_version": 1,
        "estado": initial_state,
        "fecha_programada": str(ticket.get("fecha_visita") or ""),
        "observacion_devolucion": "",
        "matafuegos": [],
        "documentos": {},
        "historial": [],
    }


def _workflow(ticket, *, create=False):
    value = ticket.get("matafuegos_portal")
    if not isinstance(value, dict):
        value = _base_workflow(ticket)
        if create:
            ticket["matafuegos_portal"] = value
    for key, default in _base_workflow(ticket).items():
        value.setdefault(key, copy.deepcopy(default))
    if value.get("estado") not in STATES:
        value["estado"] = "Pendiente"
    return value


def _find_ticket(tickets, ticket_id):
    return next((ticket for ticket in tickets if str(ticket.get("id")) == str(ticket_id)), None)


def _authorized_ticket(ticket_id, *, admin=False):
    tickets = _load_tickets()
    ticket = _find_ticket(tickets, ticket_id)
    if not ticket:
        return tickets, None, (render_template("error.html", mensaje="Ticket no encontrado."), 404)
    if not current_app.config["MATAFUEGOS_REAL_TICKET_VISIBLE"](ticket):
        return tickets, None, (render_template("error.html", mensaje="Ticket no encontrado."), 404)
    if not admin and not _ticket_allowed(ticket):
        return tickets, None, (render_template("error.html", mensaje="No tenés permiso para ver este ticket."), 403)
    return tickets, ticket, None


def _item_from_form(existing=None):
    kind = _clean(request.form.get("tipo"), "Tipo", required=True, max_length=20)
    physical = _clean(request.form.get("estado_fisico"), "Estado físico", required=True, max_length=40)
    work = _clean(request.form.get("trabajo_realizado"), "Trabajo realizado", required=True, max_length=30)
    found = _clean(request.form.get("encontrado"), "Encontrado", required=True, max_length=3)
    if kind not in EXTINGUISHER_TYPES or physical not in PHYSICAL_STATES or work not in WORK_TYPES or found not in ("si", "no"):
        raise ValidationError("Uno de los valores seleccionados no es válido.")
    recharge = _date(request.form.get("fecha_recarga"), "Fecha de recarga")
    expiry = _date(request.form.get("proximo_vencimiento"), "Próximo vencimiento")
    if expiry <= recharge:
        raise ValidationError("El próximo vencimiento debe ser posterior a la fecha de recarga.")
    item = copy.deepcopy(existing or {})
    item.update({
        "id": item.get("id") or f"EXT-{uuid.uuid4().hex[:12].upper()}",
        "activo": item.get("activo", True), "tipo": kind,
        "capacidad_kg": _capacity(request.form.get("capacidad_kg")),
        "cantidad_unidades": _quantity(request.form.get("cantidad_unidades")),
        "ubicacion": _clean(request.form.get("ubicacion"), "Ubicación", required=True, max_length=160),
        "identificacion": _clean(request.form.get("identificacion"), "Identificación", required=True, max_length=120),
        "encontrado": found, "estado_fisico": physical, "trabajo_realizado": work,
        "fecha_recarga": recharge, "proximo_vencimiento": expiry,
        "observacion": _clean(request.form.get("observacion"), "Observación", max_length=1000),
        "fotos_antes": list(item.get("fotos_antes") or []), "fotos_despues": list(item.get("fotos_despues") or []),
        "actualizado": _now(),
    })
    item.setdefault("creado", _now())
    return item


def _signature_ok(ext, content):
    return ((ext == ".pdf" and content.startswith(b"%PDF-")) or
            (ext in (".jpg", ".jpeg") and content.startswith(b"\xff\xd8\xff")) or
            (ext == ".png" and content.startswith(b"\x89PNG\r\n\x1a\n")) or
            (ext == ".webp" and len(content) >= 12 and content.startswith(b"RIFF") and content[8:12] == b"WEBP"))


def _prepare_upload(storage, label, allowed):
    if not storage or not storage.filename:
        return None
    original = Path(storage.filename).name
    if original != storage.filename or original in (".", ".."):
        raise ValidationError(f"El nombre de archivo de {label} es inválido.")
    ext = Path(original).suffix.lower()
    if ext not in allowed:
        raise ValidationError(f"El formato de {label} no está permitido.")
    max_bytes = min(int(current_app.config.get("MATAFUEGOS_REAL_MAX_FILE_BYTES", 10 * 1024 * 1024)), int(current_app.config.get("MAX_CONTENT_LENGTH") or 60 * 1024 * 1024))
    content = storage.stream.read(max_bytes + 1)
    if not content or len(content) > max_bytes or not _signature_ok(ext, content):
        raise ValidationError(f"El archivo de {label} está vacío, excede el límite o no coincide con su extensión.")
    return {"nombre_original": _clean(original, f"Nombre de {label}", required=True, max_length=180), "archivo": f"{uuid.uuid4().hex}{ext}", "tamano": len(content), "contenido": content}


def _ticket_dir(ticket_id):
    root = Path(current_app.config["MATAFUEGOS_REAL_UPLOADS_DIR"])
    return root / str(ticket_id)


def _persist_uploads(ticket_id, uploads):
    created = []
    directory = _ticket_dir(ticket_id)
    directory.mkdir(parents=True, exist_ok=True)
    try:
        for upload in uploads:
            destination = directory / upload["archivo"]
            temp = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
            temp.write_bytes(upload["contenido"])
            os.replace(temp, destination)
            created.append(destination)
        return created
    except Exception:
        for path in created:
            path.unlink(missing_ok=True)
        raise


def _metadata(upload):
    return {key: upload[key] for key in ("nombre_original", "archivo", "tamano")}


def _assert_editable(workflow):
    if workflow.get("estado") not in ("Pendiente", "Programado"):
        raise ValidationError("El trabajo no admite edición en su estado actual.")


def _validate_completion(workflow):
    if workflow.get("estado") != "Programado":
        raise ValidationError("Sólo un trabajo Programado puede pasar a Realizado.")
    active = [item for item in workflow.get("matafuegos", []) if item.get("activo", True)]
    if not active:
        raise ValidationError("Debe haber al menos un matafuego activo.")
    for item in active:
        if any(item.get(key) in (None, "", 0) for key in ("tipo", "capacidad_kg", "cantidad_unidades", "ubicacion", "identificacion", "encontrado", "estado_fisico", "trabajo_realizado", "fecha_recarga", "proximo_vencimiento")):
            raise ValidationError("Todos los matafuegos activos deben tener sus datos mínimos completos.")
        if _date(item.get("proximo_vencimiento"), "Próximo vencimiento") <= _date(item.get("fecha_recarga"), "Fecha de recarga"):
            raise ValidationError("Cada vencimiento debe ser posterior a su fecha de recarga.")


def _ticket_view(ticket, *, admin):
    return render_template("matafuegos_real_detalle.html", ticket=ticket, orden=_workflow(ticket), is_admin=admin,
                           estados=STATES, tipos=EXTINGUISHER_TYPES, estados_fisicos=PHYSICAL_STATES,
                           trabajos=WORK_TYPES, capacidades=CAPACITY_PRESETS, hoy=_today().isoformat(),
                           adjuntos_existentes=_existing_attachments(ticket))


def _existing_attachments(ticket):
    found = []
    seen = set()
    def walk(value, key=""):
        if isinstance(value, dict):
            for child_key, child in value.items():
                if child_key != "matafuegos_portal":
                    walk(child, child_key)
        elif isinstance(value, list):
            for child in value: walk(child, key)
        elif isinstance(value, str) and key.lower() in {"archivo", "adjunto", "foto", "fotos", "remito", "certificado"}:
            name = Path(value).name
            if name == value and name not in seen:
                seen.add(name); found.append(name)
    for key, value in ticket.items():
        if key != "matafuegos_portal": walk(value, key)
    return found


def _panel_orders(*, admin=False):
    tickets = _load_tickets()
    if admin:
        # Administración ve únicamente tickets asignados a una cuenta de tipo matafuegos.
        matcher = current_app.config["MATAFUEGOS_REAL_ADMIN_TICKET_ALLOWED"]
        tickets = [
            ticket for ticket in tickets
            if current_app.config["MATAFUEGOS_REAL_TICKET_VISIBLE"](ticket) and matcher(ticket)
        ]
    else:
        tickets = [ticket for ticket in tickets if _ticket_allowed(ticket)]
    return tickets


@real_bp.get("/proveedor/matafuegos")
@real_required
def panel():
    state_filter = request.args.get("estado", "").strip()
    if state_filter not in STATES: state_filter = ""
    tickets = _panel_orders()
    counts = {state: sum(_workflow(ticket)["estado"] == state for ticket in tickets) for state in STATES}
    filtered = [ticket for ticket in tickets if not state_filter or _workflow(ticket)["estado"] == state_filter]
    return render_template("matafuegos_real_panel.html", ordenes=[(ticket, _workflow(ticket)) for ticket in filtered], conteos=counts, estados=STATES, filtro_estado=state_filter, is_admin=False)


@real_bp.get("/proveedor/matafuegos/ticket/<int:ticket_id>")
@real_required
def detail(ticket_id):
    _, ticket, error = _authorized_ticket(ticket_id)
    return error or _ticket_view(ticket, admin=False)


@real_bp.post("/proveedor/matafuegos/ticket/<int:ticket_id>/programar")
@real_required
def schedule(ticket_id):
    invalid = _csrf_required()
    if invalid: return invalid
    tickets, ticket, error = _authorized_ticket(ticket_id)
    if error: return error
    try:
        workflow = _workflow(ticket, create=True)
        if workflow["estado"] != "Pendiente": raise ValidationError("Sólo un trabajo Pendiente puede programarse.")
        date = _date(request.form.get("fecha_programada"), "Fecha programada")
        if date < _today().isoformat(): raise ValidationError("La fecha programada no puede estar en el pasado.")
        workflow.update(estado="Programado", fecha_programada=date, observacion_devolucion="")
        workflow["historial"].append(_history(session.get("prov_nombre", "Proveedor"), "Programado", date))
        _save_tickets(tickets); flash("Visita programada.")
    except ValidationError as exc: flash(str(exc))
    return redirect(url_for("matafuegos_real.detail", ticket_id=ticket_id))


def _item_action(ticket_id, item_id=None):
    tickets, ticket, error = _authorized_ticket(ticket_id)
    if error: return error
    workflow = _workflow(ticket, create=True)
    existing = next((item for item in workflow["matafuegos"] if item.get("id") == item_id), None) if item_id else None
    if item_id and (not ID_RE.fullmatch(item_id) or not existing):
        return render_template("error.html", mensaje="Matafuego no encontrado."), 404
    created = []
    try:
        _assert_editable(workflow)
        if existing and not existing.get("activo", True): raise ValidationError("Un matafuego anulado no puede editarse.")
        item = _item_from_form(existing)
        before = _prepare_upload(request.files.get("foto_antes"), "foto antes", IMAGE_EXTENSIONS)
        after = _prepare_upload(request.files.get("foto_despues"), "foto después", IMAGE_EXTENSIONS)
        uploads = [u for u in (before, after) if u]
        created = _persist_uploads(ticket_id, uploads) if uploads else []
        if before: item["fotos_antes"].append(_metadata(before))
        if after: item["fotos_despues"].append(_metadata(after))
        if existing: existing.clear(); existing.update(item); action = "Matafuego editado"
        else: workflow["matafuegos"].append(item); action = "Matafuego agregado"
        workflow["historial"].append(_history(session.get("prov_nombre", "Proveedor"), action, item["identificacion"]))
        _save_tickets(tickets); flash("Relevamiento actualizado.")
    except ValidationError as exc:
        for path in created: path.unlink(missing_ok=True)
        flash(str(exc))
    except Exception:
        for path in created: path.unlink(missing_ok=True)
        raise
    return redirect(url_for("matafuegos_real.detail", ticket_id=ticket_id))


@real_bp.post("/proveedor/matafuegos/ticket/<int:ticket_id>/matafuegos")
@real_required
def add_item(ticket_id):
    invalid = _csrf_required()
    return invalid or _item_action(ticket_id)


@real_bp.post("/proveedor/matafuegos/ticket/<int:ticket_id>/matafuegos/<item_id>")
@real_required
def edit_item(ticket_id, item_id):
    invalid = _csrf_required()
    return invalid or _item_action(ticket_id, item_id)


@real_bp.post("/proveedor/matafuegos/ticket/<int:ticket_id>/matafuegos/<item_id>/anular")
@real_required
def void_item(ticket_id, item_id):
    invalid = _csrf_required()
    if invalid: return invalid
    tickets, ticket, error = _authorized_ticket(ticket_id)
    if error: return error
    workflow = _workflow(ticket, create=True)
    item = next((entry for entry in workflow["matafuegos"] if entry.get("id") == item_id), None)
    if not item or not ID_RE.fullmatch(item_id): return render_template("error.html", mensaje="Matafuego no encontrado."), 404
    try:
        _assert_editable(workflow)
        if not item.get("activo", True): raise ValidationError("El matafuego ya está anulado.")
        reason = _clean(request.form.get("motivo"), "Motivo", required=True, max_length=500)
        item.update(activo=False, anulado_motivo=reason, anulado_fecha=_now())
        workflow["historial"].append(_history(session.get("prov_nombre", "Proveedor"), "Matafuego anulado", reason))
        _save_tickets(tickets); flash("Matafuego anulado sin borrar su historial.")
    except ValidationError as exc: flash(str(exc))
    return redirect(url_for("matafuegos_real.detail", ticket_id=ticket_id))


@real_bp.post("/proveedor/matafuegos/ticket/<int:ticket_id>/finalizar")
@real_required
def complete(ticket_id):
    invalid = _csrf_required()
    if invalid: return invalid
    tickets, ticket, error = _authorized_ticket(ticket_id)
    if error: return error
    workflow = _workflow(ticket, create=True); created = []
    try:
        _validate_completion(workflow)
        remito = _prepare_upload(request.files.get("remito"), "remito", DOCUMENT_EXTENSIONS)
        certificate = _prepare_upload(request.files.get("certificado"), "certificado", DOCUMENT_EXTENSIONS)
        if not remito or not certificate: raise ValidationError("El remito y el certificado son obligatorios para finalizar.")
        created = _persist_uploads(ticket_id, [remito, certificate])
        workflow["documentos"] = {"remito": _metadata(remito), "certificado": _metadata(certificate)}
        workflow["estado"] = "Realizado"
        workflow["historial"].append(_history(session.get("prov_nombre", "Proveedor"), "Realizado", "Remito y certificado adjuntos"))
        _save_tickets(tickets); flash("Trabajo marcado como Realizado y enviado a validación.")
    except ValidationError as exc:
        for path in created: path.unlink(missing_ok=True)
        flash(str(exc))
    except Exception:
        for path in created: path.unlink(missing_ok=True)
        raise
    return redirect(url_for("matafuegos_real.detail", ticket_id=ticket_id))


@real_bp.get("/admin/proveedores/matafuegos")
@admin_required
def admin_panel():
    state_filter = request.args.get("estado", "").strip()
    if state_filter not in STATES: state_filter = ""
    tickets = _panel_orders(admin=True)
    counts = {state: sum(_workflow(ticket)["estado"] == state for ticket in tickets) for state in STATES}
    filtered = [ticket for ticket in tickets if not state_filter or _workflow(ticket)["estado"] == state_filter]
    return render_template("matafuegos_real_panel.html", ordenes=[(ticket, _workflow(ticket)) for ticket in filtered], conteos=counts, estados=STATES, filtro_estado=state_filter, is_admin=True)


@real_bp.get("/admin/proveedores/matafuegos/ticket/<int:ticket_id>")
@admin_required
def admin_detail(ticket_id):
    _, ticket, error = _authorized_ticket(ticket_id, admin=True)
    if error: return error
    if not current_app.config["MATAFUEGOS_REAL_ADMIN_TICKET_ALLOWED"](ticket):
        return render_template("error.html", mensaje="El ticket no corresponde al portal de matafuegos."), 404
    return _ticket_view(ticket, admin=True)


def _admin_transition(ticket_id, validate):
    invalid = _csrf_required()
    if invalid: return invalid
    tickets, ticket, error = _authorized_ticket(ticket_id, admin=True)
    if error: return error
    if not current_app.config["MATAFUEGOS_REAL_ADMIN_TICKET_ALLOWED"](ticket): return render_template("error.html", mensaje="Ticket no encontrado."), 404
    workflow = _workflow(ticket, create=True)
    try:
        if workflow["estado"] != "Realizado": raise ValidationError("Sólo un trabajo Realizado puede revisarse.")
        if validate:
            _validate_completion_records(workflow)
            workflow["estado"] = "Validado"; detail = "Trabajo aprobado"; action = "Validado"
        else:
            detail = _clean(request.form.get("observacion"), "Observación de devolución", required=True, max_length=1000)
            workflow.update(estado="Pendiente", fecha_programada="", observacion_devolucion=detail); action = "Devuelto para corregir"
        workflow["historial"].append(_history(session.get("nombre", "Admin"), action, detail))
        _save_tickets(tickets); flash("Trabajo validado." if validate else "Trabajo devuelto para corregir.")
    except ValidationError as exc: flash(str(exc))
    return redirect(url_for("matafuegos_real.admin_detail", ticket_id=ticket_id))


@real_bp.post("/admin/proveedores/matafuegos/ticket/<int:ticket_id>/validar")
@admin_required
def validate(ticket_id): return _admin_transition(ticket_id, True)


@real_bp.post("/admin/proveedores/matafuegos/ticket/<int:ticket_id>/devolver")
@admin_required
def return_for_changes(ticket_id): return _admin_transition(ticket_id, False)


def _validate_completion_records(workflow):
    active = [item for item in workflow.get("matafuegos", []) if item.get("activo", True)]
    if not active:
        raise ValidationError("No se puede validar sin al menos un matafuego activo relevado.")
    documents = workflow.get("documentos") or {}
    if not documents.get("remito") or not documents.get("certificado"):
        raise ValidationError("No se puede validar sin remito y certificado.")
    # Reutiliza las mismas validaciones de campos y fechas sin exigir que el
    # estado continúe Programado.
    probe = copy.deepcopy(workflow)
    probe["estado"] = "Programado"
    _validate_completion(probe)


def _referenced(workflow, filename):
    if Path(filename).name != filename or not REAL_UPLOAD_RE.fullmatch(filename): return False
    for document in workflow.get("documentos", {}).values():
        if document.get("archivo") == filename: return True
    for item in workflow.get("matafuegos", []):
        for key in ("fotos_antes", "fotos_despues"):
            if any(photo.get("archivo") == filename for photo in item.get(key, [])): return True
    return False


@real_bp.get("/proveedor/matafuegos/ticket/<int:ticket_id>/archivo/<filename>")
def serve_file(ticket_id, filename):
    is_admin = bool(
        session.get("user") and session.get("rol") == "admin" and _session_valid()
        and (session.get("auth_provider") != "entra" or session.get("entra_role") == "admin")
    )
    is_provider = bool(session.get("prov_user") and _session_valid() and _refresh_session() == "matafuegos")
    if not (is_admin or is_provider): return render_template("error.html", mensaje="Acceso restringido al archivo."), 403
    _, ticket, error = _authorized_ticket(ticket_id, admin=is_admin)
    if error: return error
    if is_admin and not current_app.config["MATAFUEGOS_REAL_ADMIN_TICKET_ALLOWED"](ticket): return render_template("error.html", mensaje="Archivo no encontrado."), 404
    if not _referenced(_workflow(ticket), filename): return render_template("error.html", mensaje="Archivo no encontrado."), 404
    return send_from_directory(str(_ticket_dir(ticket_id)), filename)


@real_bp.get("/proveedor/matafuegos/ticket/<int:ticket_id>/adjunto-existente/<path:filename>")
def serve_existing_file(ticket_id, filename):
    is_admin = bool(
        session.get("user") and session.get("rol") == "admin" and _session_valid()
        and (session.get("auth_provider") != "entra" or session.get("entra_role") == "admin")
    )
    is_provider = bool(session.get("prov_user") and _session_valid() and _refresh_session() == "matafuegos")
    if not (is_admin or is_provider) or Path(filename).name != filename:
        return render_template("error.html", mensaje="Acceso restringido al archivo."), 403
    _, ticket, error = _authorized_ticket(ticket_id, admin=is_admin)
    if error: return error
    if is_admin and not current_app.config["MATAFUEGOS_REAL_ADMIN_TICKET_ALLOWED"](ticket): return render_template("error.html", mensaje="Archivo no encontrado."), 404
    if filename not in _existing_attachments(ticket): return render_template("error.html", mensaje="Archivo no encontrado."), 404
    return send_from_directory(str(current_app.config["MATAFUEGOS_REAL_LEGACY_UPLOADS_DIR"]), filename)
