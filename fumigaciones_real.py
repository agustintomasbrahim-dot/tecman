"""Portal real de fumigaciones por cartera de sucursales, sin tickets."""
from __future__ import annotations

import datetime as dt
import os
import secrets
import uuid
from functools import wraps
from pathlib import Path

from flask import Blueprint, current_app, flash, redirect, render_template, request, send_from_directory, session, url_for

fumigaciones_bp = Blueprint("fumigaciones_real", __name__)
STATES = ("Programada", "Realizada", "Validada", "Devuelta")
DOCUMENT_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".webp"}


class ValidationError(ValueError):
    pass


def _now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _session_valid():
    validator = current_app.config.get("TECMAN_SESSION_AUTH_VALIDATOR")
    return bool(validator() if validator else True)


def _refresh_provider():
    callback = current_app.config.get("FUMIGACIONES_REFRESH_SESSION")
    return callback() if callback else session.get("prov_tipo_cuenta")


def provider_required(view):
    @wraps(view)
    def decorated(*args, **kwargs):
        if not session.get("prov_user") or not _session_valid():
            session.clear()
            return redirect(url_for("prov_login"))
        if _refresh_provider() != "fumigacion":
            return render_template("error.html", mensaje="Acceso restringido al portal de fumigaciones."), 403
        return view(*args, **kwargs)
    return decorated


def admin_required(view):
    @wraps(view)
    def decorated(*args, **kwargs):
        if not session.get("user") or not _session_valid():
            session.clear()
            return redirect(url_for("admin_login"))
        if session.get("rol") != "admin" or (session.get("auth_provider") == "entra" and session.get("entra_role") != "admin"):
            return render_template("error.html", mensaje="Acceso restringido. Solo administradores."), 403
        return view(*args, **kwargs)
    return decorated


def branch_required(view):
    @wraps(view)
    def decorated(*args, **kwargs):
        if not session.get("suc_user") or not _session_valid():
            session.clear()
            return redirect(url_for("suc_login"))
        return view(*args, **kwargs)
    return decorated


def _csrf_required():
    expected = str(session.get("_csrf_token") or "")
    submitted = str(request.form.get("_csrf_token") or "")
    if not expected or not submitted or not secrets.compare_digest(expected, submitted):
        return render_template("error.html", mensaje="Solicitud inválida o vencida."), 400
    return None


def _load():
    return current_app.config["FUMIGACIONES_LOAD"]()


def _save(records):
    current_app.config["FUMIGACIONES_SAVE"](records)


def _provider_names():
    return set(current_app.config["FUMIGACIONES_PROVIDER_NAMES"]())


def _portfolio(names=None):
    return current_app.config["FUMIGACIONES_PORTFOLIO"](names if names is not None else _provider_names())


def _branch_info(num):
    return current_app.config["FUMIGACIONES_BRANCH_INFO"](num)


def _clean(value, label, *, required=False, max_length=1200):
    text = " ".join(str(value or "").strip().split())
    if required and not text:
        raise ValidationError(f"{label} es obligatorio.")
    if len(text) > max_length or any(ord(char) < 32 for char in text):
        raise ValidationError(f"{label} es inválido o demasiado largo.")
    if text.startswith(("=", "+", "@")):
        raise ValidationError(f"{label} no puede comenzar con un indicador de fórmula.")
    return text


def _date(value, label):
    try:
        return dt.date.fromisoformat(str(value or "")).isoformat()
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{label} debe ser una fecha válida.") from exc


def _normalize_num(value):
    callback = current_app.config["FUMIGACIONES_NORMALIZE_BRANCH"]
    return callback(value)


def _portfolio_entry(num):
    normalized = _normalize_num(num)
    return next((entry for entry in _portfolio() if entry["sucursal_num"] == normalized), None)


def _authorized_record(record_id, *, admin=False, branch=False):
    records = _load()
    record = next((item for item in records if str(item.get("id")) == str(record_id)), None)
    if not record:
        return records, None, (render_template("error.html", mensaje="Visita no encontrada."), 404)
    if branch:
        scope = current_app.config["FUMIGACIONES_BRANCH_SCOPE"]()
        if scope is None or record.get("sucursal_num") not in scope:
            return records, None, (render_template("error.html", mensaje="No tenés acceso a esta visita."), 403)
    elif not admin:
        if record.get("proveedor") not in _provider_names() or not _portfolio_entry(record.get("sucursal_num")):
            return records, None, (render_template("error.html", mensaje="No tenés acceso a esta visita."), 403)
    return records, record, None


def _prepare_upload(storage, label, *, required=False):
    if not storage or not storage.filename:
        if required:
            raise ValidationError(f"{label} es obligatorio.")
        return None
    original = Path(storage.filename).name
    if original != storage.filename or original in (".", ".."):
        raise ValidationError(f"El nombre de {label} es inválido.")
    ext = Path(original).suffix.lower()
    if ext not in DOCUMENT_EXTENSIONS:
        raise ValidationError(f"El formato de {label} no está permitido.")
    limit = int(current_app.config.get("FUMIGACIONES_MAX_FILE_BYTES", 10 * 1024 * 1024))
    content = storage.stream.read(limit + 1)
    signatures = {
        ".pdf": content.startswith(b"%PDF-"),
        ".jpg": content.startswith(b"\xff\xd8\xff"),
        ".jpeg": content.startswith(b"\xff\xd8\xff"),
        ".png": content.startswith(b"\x89PNG\r\n\x1a\n"),
        ".webp": len(content) >= 12 and content.startswith(b"RIFF") and content[8:12] == b"WEBP",
    }
    if not content or len(content) > limit or not signatures.get(ext):
        raise ValidationError(f"{label} está vacío, excede el límite o no coincide con su extensión.")
    return {"nombre_original": _clean(original, label, required=True, max_length=180), "archivo": f"{uuid.uuid4().hex}{ext}", "tamano": len(content), "contenido": content}


def _record_dir(record_id):
    return Path(current_app.config["FUMIGACIONES_UPLOADS_DIR"]) / str(record_id)


def _persist(record_id, uploads):
    directory = _record_dir(record_id)
    directory.mkdir(parents=True, exist_ok=True)
    created = []
    try:
        for upload in uploads:
            destination = directory / upload["archivo"]
            temp = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
            temp.write_bytes(upload["contenido"])
            os.replace(temp, destination)
            created.append(destination)
    except Exception:
        for path in created:
            path.unlink(missing_ok=True)
        raise
    return created


def _metadata(upload):
    return {key: upload[key] for key in ("nombre_original", "archivo", "tamano")}


def _history(actor, action, detail=""):
    return {"fecha": _now(), "actor": actor, "accion": action, "detalle": detail}


def _branch_card(entry, records):
    own = [record for record in records if record.get("sucursal_num") == entry["sucursal_num"] and record.get("proveedor") == entry["proveedor"]]
    own.sort(key=lambda item: (item.get("fecha_programada", ""), item.get("creado", "")), reverse=True)
    return {**entry, "info": _branch_info(entry["sucursal_num"]), "visitas": own, "ultima": own[0] if own else None}


@fumigaciones_bp.get("/proveedor/fumigaciones")
@provider_required
def panel():
    records = _load()
    cards = [_branch_card(entry, records) for entry in _portfolio()]
    query = _clean(request.args.get("q"), "Búsqueda", max_length=80).casefold()
    if query:
        cards = [card for card in cards if query in " ".join((card["sucursal_num"], card.get("sucursal", ""), str(card.get("info", {}).get("direccion", "")))).casefold()]
    return render_template("fumigaciones_real_panel.html", sucursales=cards, q=query, is_admin=False)


@fumigaciones_bp.get("/proveedor/fumigaciones/sucursal/<sucursal_num>")
@provider_required
def detail(sucursal_num):
    entry = _portfolio_entry(sucursal_num)
    if not entry:
        return render_template("error.html", mensaje="No tenés acceso a esta sucursal."), 403
    card = _branch_card(entry, _load())
    return render_template("fumigaciones_real_detalle.html", sucursal=card, visitas=card["visitas"], is_admin=False, hoy=dt.date.today().isoformat())


@fumigaciones_bp.post("/proveedor/fumigaciones/sucursal/<sucursal_num>/programar")
@provider_required
def schedule(sucursal_num):
    invalid = _csrf_required()
    if invalid:
        return invalid
    entry = _portfolio_entry(sucursal_num)
    if not entry:
        return render_template("error.html", mensaje="No tenés acceso a esta sucursal."), 403
    try:
        date = _date(request.form.get("fecha_programada"), "Fecha programada")
        if date < dt.date.today().isoformat():
            raise ValidationError("La fecha programada no puede estar en el pasado.")
        note = _clean(request.form.get("observacion"), "Observación", max_length=500)
    except ValidationError as exc:
        return render_template("error.html", mensaje=str(exc)), 400
    records = _load()
    duplicate = next((record for record in records if record.get("proveedor") == entry["proveedor"] and record.get("sucursal_num") == entry["sucursal_num"] and record.get("fecha_programada") == date), None)
    if duplicate:
        flash("La visita ya estaba programada; no se duplicó la notificación.")
        return redirect(url_for("fumigaciones_real.detail", sucursal_num=entry["sucursal_num"]))
    record_id = f"FUM-{uuid.uuid4().hex[:12].upper()}"
    now = _now()
    text = f"Fumigación programada para {date} por {entry['proveedor']}."
    record = {
        "id": record_id, "schema_version": 1, "sucursal_num": entry["sucursal_num"],
        "sucursal": entry["sucursal"], "proveedor": entry["proveedor"], "estado": "Programada",
        "fecha_programada": date, "observacion_programacion": note, "creado": now, "actualizado": now,
        "relevamiento": {}, "documentos": {},
        "notificaciones_sucursal": [{"clave": f"fumigacion_programada:{entry['proveedor']}:{entry['sucursal_num']}:{date}", "fecha": now, "texto": text, "leida": False}],
        "historial": [_history(session.get("prov_nombre", "Proveedor"), "Visita programada", text)],
    }
    records.append(record)
    _save(records)
    flash("Visita programada y sucursal notificada.")
    return redirect(url_for("fumigaciones_real.detail", sucursal_num=entry["sucursal_num"]))


@fumigaciones_bp.post("/proveedor/fumigaciones/visita/<record_id>/relevamiento")
@provider_required
def complete(record_id):
    invalid = _csrf_required()
    if invalid:
        return invalid
    records, record, error = _authorized_record(record_id)
    if error:
        return error
    if record.get("estado") not in ("Programada", "Devuelta"):
        return render_template("error.html", mensaje="La visita no admite un nuevo relevamiento."), 409
    created = []
    try:
        work = _clean(request.form.get("trabajo_realizado"), "Trabajo realizado", required=True)
        pests = _clean(request.form.get("plagas_detectadas"), "Plagas detectadas")
        products = _clean(request.form.get("productos_aplicados"), "Productos aplicados", required=True)
        observations = _clean(request.form.get("observaciones"), "Observaciones")
        visit_date = _date(request.form.get("fecha_realizada"), "Fecha realizada")
        remito = _prepare_upload(request.files.get("remito"), "Remito", required=True)
        certificate = _prepare_upload(request.files.get("certificado"), "Certificado")
        evidence = _prepare_upload(request.files.get("evidencia"), "Evidencia")
        uploads = [item for item in (remito, certificate, evidence) if item]
        created = _persist(record_id, uploads)
        record["relevamiento"] = {"fecha_realizada": visit_date, "trabajo_realizado": work, "plagas_detectadas": pests, "productos_aplicados": products, "observaciones": observations}
        record["documentos"] = {"remito": _metadata(remito)}
        if certificate:
            record["documentos"]["certificado"] = _metadata(certificate)
        if evidence:
            record["documentos"]["evidencia"] = _metadata(evidence)
        record.update(estado="Realizada", actualizado=_now(), observacion_devolucion="")
        record.setdefault("historial", []).append(_history(session.get("prov_nombre", "Proveedor"), "Relevamiento registrado", work))
        _save(records)
    except ValidationError as exc:
        for path in created:
            path.unlink(missing_ok=True)
        return render_template("error.html", mensaje=str(exc)), 400
    except Exception:
        for path in created:
            path.unlink(missing_ok=True)
        raise
    flash("Relevamiento y documentación enviados a validación.")
    return redirect(url_for("fumigaciones_real.detail", sucursal_num=record["sucursal_num"]))


@fumigaciones_bp.get("/suc/fumigaciones/visita/<record_id>/archivo/<filename>")
@fumigaciones_bp.get("/proveedor/fumigaciones/visita/<record_id>/archivo/<filename>")
def serve_file(record_id, filename):
    admin = bool(session.get("user") and session.get("rol") == "admin" and _session_valid())
    provider = bool(session.get("prov_user") and _session_valid() and _refresh_provider() == "fumigacion")
    branch = bool(session.get("suc_user") and _session_valid())
    if not (admin or provider or branch):
        return render_template("error.html", mensaje="Acceso restringido al archivo."), 403
    _, record, error = _authorized_record(record_id, admin=admin, branch=branch)
    if error:
        return error
    if Path(filename).name != filename or not any(doc.get("archivo") == filename for doc in record.get("documentos", {}).values()):
        return render_template("error.html", mensaje="Archivo no encontrado."), 404
    return send_from_directory(str(_record_dir(record_id)), filename)


@fumigaciones_bp.get("/admin/proveedores/fumigaciones")
@admin_required
def admin_panel():
    records = _load()
    records.sort(key=lambda item: (item.get("fecha_programada", ""), item.get("creado", "")), reverse=True)
    return render_template("fumigaciones_admin_panel.html", visitas=records)


@fumigaciones_bp.get("/admin/proveedores/fumigaciones/visita/<record_id>")
@admin_required
def admin_detail(record_id):
    _, record, error = _authorized_record(record_id, admin=True)
    if error:
        return error
    entry = {"sucursal_num": record["sucursal_num"], "sucursal": record.get("sucursal", f"Sucursal {record['sucursal_num']}"), "proveedor": record["proveedor"]}
    return render_template("fumigaciones_real_detalle.html", sucursal=_branch_card(entry, _load()), visitas=[record], is_admin=True, hoy=dt.date.today().isoformat())


def _admin_transition(record_id, validate):
    invalid = _csrf_required()
    if invalid:
        return invalid
    records, record, error = _authorized_record(record_id, admin=True)
    if error:
        return error
    if record.get("estado") != "Realizada":
        return render_template("error.html", mensaje="Sólo una visita realizada puede revisarse."), 409
    if validate:
        if not record.get("documentos", {}).get("remito") or not record.get("relevamiento", {}).get("trabajo_realizado"):
            return render_template("error.html", mensaje="El relevamiento o remito está incompleto."), 409
        record.update(estado="Validada", observacion_devolucion="", actualizado=_now())
        action, detail = "Visita validada", "Documentación aprobada"
    else:
        try:
            detail = _clean(request.form.get("observacion"), "Observación", required=True, max_length=1000)
        except ValidationError as exc:
            return render_template("error.html", mensaje=str(exc)), 400
        record.update(estado="Devuelta", observacion_devolucion=detail, actualizado=_now())
        action = "Devuelta para corregir"
    record.setdefault("historial", []).append(_history(session.get("nombre", "Administración"), action, detail))
    _save(records)
    flash("Visita validada." if validate else "Visita devuelta para corregir.")
    return redirect(url_for("fumigaciones_real.admin_detail", record_id=record_id))


@fumigaciones_bp.post("/admin/proveedores/fumigaciones/visita/<record_id>/validar")
@admin_required
def validate(record_id):
    return _admin_transition(record_id, True)


@fumigaciones_bp.post("/admin/proveedores/fumigaciones/visita/<record_id>/devolver")
@admin_required
def return_for_changes(record_id):
    return _admin_transition(record_id, False)


def branch_visits(scope):
    """Proyección read-only usada por la vista interna de la sucursal."""
    if scope is None:
        return []
    records = [record for record in _load() if record.get("sucursal_num") in scope]
    records.sort(key=lambda item: (item.get("fecha_programada", ""), item.get("creado", "")), reverse=True)
    return records
