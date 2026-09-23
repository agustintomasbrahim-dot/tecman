"""Portal operativo de matafuegos por cartera de sucursales e inventario real.

Las cuentas de proveedor ven exclusivamente las sucursales asignadas en su
cartera. Cada visita se persiste separada de tickets; la validación
administrativa incorpora el relevamiento al inventario real conservando
historial y auditoría.
"""
from __future__ import annotations

import copy
import datetime as dt
import os
import re
import secrets
import uuid
from functools import wraps
from pathlib import Path

from flask import Blueprint, current_app, flash, redirect, render_template, request, send_from_directory, session, url_for

real_bp = Blueprint("matafuegos_real", __name__)

STATES = ("Pendiente", "Programado", "Realizado", "Validado", "Devuelto")
PHYSICAL_STATES = ("Bueno", "Regular", "Malo", "Fuera de servicio")
WORK_TYPES = ("sin intervención", "recargado", "reparado", "reemplazado", "rechazado", "otro")
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
DOCUMENT_EXTENSIONS = IMAGE_EXTENSIONS | {".pdf"}
ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
UPLOAD_RE = re.compile(r"^[a-f0-9]{32}\.(?:pdf|jpg|jpeg|png|webp)$")


class ValidationError(ValueError):
    pass


def _load_inventory():
    return current_app.config["MATAFUEGOS_REAL_LOAD_INVENTORY"]()


def _save_inventory(data):
    current_app.config["MATAFUEGOS_REAL_SAVE_INVENTORY"](data)


def _load_visits():
    return current_app.config["MATAFUEGOS_REAL_LOAD_VISITS"]()


def _save_visits(data):
    current_app.config["MATAFUEGOS_REAL_SAVE_VISITS"](data)


def _portfolio():
    return current_app.config["MATAFUEGOS_REAL_PROVIDER_PORTFOLIO"]()


def _admin_portfolio():
    return current_app.config["MATAFUEGOS_REAL_ADMIN_PORTFOLIO"]()


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


def _branch_num(value):
    raw = str(value or "").replace("Sucursal", "").strip()
    if not raw.isdigit() or len(raw) > 6:
        return ""
    return raw.zfill(3)


def _actor():
    return session.get("prov_nombre") or session.get("nombre") or session.get("prov_user") or session.get("user") or "Sistema"


def _history(action, detail=""):
    return {"fecha": _now(), "actor": _actor(), "accion": action, "detalle": str(detail or "")}


def _provider_key():
    return str(session.get("prov_user") or "").strip().lower()


def _provider_name():
    return str(session.get("prov_nombre") or session.get("prov_user") or "Proveedor").strip()


def _inventory_items(branch):
    return [item for item in _load_inventory().get("matafuegos", []) if _branch_num(item.get("sucursal_num") or item.get("sucursal")) == branch]


def _branch_summary(branch, items):
    first = items[0] if items else {}
    return {
        "sucursal_num": branch,
        "sucursal": first.get("sucursal") or f"Sucursal {branch}",
        "local_nombre": first.get("local_nombre") or "",
        "cantidad": sum(int(item.get("cantidad") or 1) for item in items),
        "registros": len(items),
    }


def _visits(data=None):
    return (data or _load_visits()).setdefault("visitas", [])


def _latest_visit(branch, *, provider_key=None, data=None):
    matches = [visit for visit in _visits(data) if _branch_num(visit.get("sucursal_num")) == branch]
    if provider_key is not None:
        matches = [visit for visit in matches if visit.get("proveedor_key") == provider_key]
    return max(matches, key=lambda value: (value.get("creado") or "", value.get("id") or ""), default=None)


def _find_visit(data, visit_id):
    return next((visit for visit in _visits(data) if visit.get("id") == visit_id), None)


def _authorized_branch(branch, *, admin=False):
    normalized = _branch_num(branch)
    portfolio = _admin_portfolio() if admin else _portfolio()
    if not normalized or normalized not in portfolio:
        return normalized, None, (render_template("error.html", mensaje="Sucursal fuera de la cartera autorizada."), 403)
    return normalized, portfolio[normalized], None


def _new_visit(branch, provider_key, provider_name):
    return {
        "id": f"VIS-{uuid.uuid4().hex[:16].upper()}",
        "schema_version": 2,
        "sucursal_num": branch,
        "sucursal": f"Sucursal {branch}",
        "proveedor_key": provider_key,
        "proveedor": provider_name,
        "estado": "Pendiente",
        "fecha_programada": "",
        "avisos_sucursal": [],
        "resultados": {},
        "documentos": {},
        "observacion_devolucion": "",
        "historial": [],
        "creado": _now(),
        "actualizado": _now(),
    }


def _provider_visit(branch, *, create=False, data=None):
    data = data or _load_visits()
    visit = _latest_visit(branch, provider_key=_provider_key(), data=data)
    if create and (not visit or visit.get("estado") == "Validado"):
        visit = _new_visit(branch, _provider_key(), _provider_name())
        _visits(data).append(visit)
    return data, visit


def _editable(visit):
    if not visit or visit.get("estado") not in ("Programado", "Devuelto"):
        raise ValidationError("La visita debe estar Programada o Devuelta para editar el relevamiento.")


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


def _visit_dir(visit_id):
    return Path(current_app.config["MATAFUEGOS_REAL_UPLOADS_DIR"]) / visit_id


def _persist_uploads(visit_id, uploads):
    created = []
    directory = _visit_dir(visit_id)
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


def _item_result(item, existing=None):
    found = _clean(request.form.get("encontrado"), "Encontrado", required=True, max_length=3)
    physical = _clean(request.form.get("estado_fisico"), "Estado físico", required=True, max_length=40)
    work = _clean(request.form.get("trabajo_realizado"), "Trabajo realizado", required=True, max_length=40)
    if found not in ("si", "no") or physical not in PHYSICAL_STATES or work not in WORK_TYPES:
        raise ValidationError("Uno de los valores seleccionados no es válido.")
    recharge = _date(request.form.get("fecha_recarga"), "Fecha de recarga")
    expiry = _date(request.form.get("proximo_vencimiento"), "Próximo vencimiento")
    if expiry <= recharge:
        raise ValidationError("El próximo vencimiento debe ser posterior a la fecha de recarga.")
    result = copy.deepcopy(existing or {})
    result.update({
        "matafuego_id": item["id"],
        "encontrado": found,
        "estado_fisico": physical,
        "trabajo_realizado": work,
        "fecha_recarga": recharge,
        "proximo_vencimiento": expiry,
        "identificacion": _clean(request.form.get("identificacion"), "Identificación / serie", required=True, max_length=120),
        "ubicacion": _clean(request.form.get("ubicacion"), "Ubicación", required=True, max_length=160),
        "observacion": _clean(request.form.get("observacion"), "Observación", max_length=1000),
        "fotos_antes": list(result.get("fotos_antes") or []),
        "fotos_despues": list(result.get("fotos_despues") or []),
        "actualizado": _now(),
    })
    return result


def _referenced(visit, filename):
    if Path(filename).name != filename or not UPLOAD_RE.fullmatch(filename):
        return False
    for document in (visit.get("documentos") or {}).values():
        values = document if isinstance(document, list) else [document]
        if any(value.get("archivo") == filename for value in values if isinstance(value, dict)):
            return True
    for result in (visit.get("resultados") or {}).values():
        for key in ("fotos_antes", "fotos_despues"):
            if any(photo.get("archivo") == filename for photo in result.get(key, [])):
                return True
    return False


def _view(branch, owner, visit, *, admin):
    items = _inventory_items(branch)
    return render_template(
        "matafuegos_real_detalle.html", branch=_branch_summary(branch, items), owner=owner,
        visita=visit, matafuegos=items, is_admin=admin, estados=STATES,
        estados_fisicos=PHYSICAL_STATES, trabajos=WORK_TYPES, hoy=_today().isoformat(),
    )


@real_bp.get("/proveedor/matafuegos")
@real_required
def panel():
    visits = _load_visits()
    branches = []
    for branch, owner in sorted(_portfolio().items()):
        items = _inventory_items(branch)
        branches.append((_branch_summary(branch, items), owner, _latest_visit(branch, provider_key=_provider_key(), data=visits)))
    return render_template("matafuegos_real_panel.html", sucursales=branches, is_admin=False)


@real_bp.get("/proveedor/matafuegos/sucursal/<branch>")
@real_required
def detail(branch):
    branch, owner, error = _authorized_branch(branch)
    if error:
        return error
    _, visit = _provider_visit(branch)
    return _view(branch, owner, visit, admin=False)


@real_bp.post("/proveedor/matafuegos/sucursal/<branch>/programar")
@real_required
def schedule(branch):
    invalid = _csrf_required()
    if invalid:
        return invalid
    branch, owner, error = _authorized_branch(branch)
    if error:
        return error
    data, visit = _provider_visit(branch, create=True)
    try:
        if visit.get("estado") not in ("Pendiente", "Programado"):
            raise ValidationError("La visita no admite reprogramación en su estado actual.")
        date = _date(request.form.get("fecha_programada"), "Fecha programada")
        if date < _today().isoformat():
            raise ValidationError("La fecha programada no puede estar en el pasado.")
        key = f"visita:{visit['id']}:{date}"
        duplicate = any(notice.get("clave") == key for notice in visit.get("avisos_sucursal", []))
        if not duplicate:
            visit.update(estado="Programado", fecha_programada=date, observacion_devolucion="", actualizado=_now())
            visit.setdefault("avisos_sucursal", []).append({"clave": key, "fecha": _now(), "fecha_programada": date, "texto": f"{visit['proveedor']} programó una visita de matafuegos para el {date}."})
            visit.setdefault("historial", []).append(_history("Visita programada y sucursal avisada", date))
            _save_visits(data)
            notifier = current_app.config.get("MATAFUEGOS_REAL_NOTIFY_SCHEDULE")
            if notifier:
                notifier(visit, owner)
        flash("Visita programada y sucursal avisada." if not duplicate else "La sucursal ya estaba avisada para esa fecha.")
    except ValidationError as exc:
        flash(str(exc))
    return redirect(url_for("matafuegos_real.detail", branch=branch))


@real_bp.post("/proveedor/matafuegos/sucursal/<branch>/equipo/<item_id>")
@real_required
def review_item(branch, item_id):
    invalid = _csrf_required()
    if invalid:
        return invalid
    branch, _, error = _authorized_branch(branch)
    if error:
        return error
    data, visit = _provider_visit(branch)
    item = next((entry for entry in _inventory_items(branch) if str(entry.get("id")) == item_id), None)
    if not ID_RE.fullmatch(item_id) or not item:
        return render_template("error.html", mensaje="Matafuego no encontrado."), 404
    created = []
    try:
        _editable(visit)
        existing = (visit.get("resultados") or {}).get(item_id)
        result = _item_result(item, existing)
        before = _prepare_upload(request.files.get("foto_antes"), "foto antes", IMAGE_EXTENSIONS)
        after = _prepare_upload(request.files.get("foto_despues"), "foto después", IMAGE_EXTENSIONS)
        uploads = [upload for upload in (before, after) if upload]
        created = _persist_uploads(visit["id"], uploads) if uploads else []
        if before:
            result["fotos_antes"].append(_metadata(before))
        if after:
            result["fotos_despues"].append(_metadata(after))
        visit.setdefault("resultados", {})[item_id] = result
        visit["actualizado"] = _now()
        visit.setdefault("historial", []).append(_history("Matafuego relevado", result["identificacion"]))
        _save_visits(data)
        flash("Relevamiento del matafuego guardado.")
    except ValidationError as exc:
        for path in created:
            path.unlink(missing_ok=True)
        flash(str(exc))
    except Exception:
        for path in created:
            path.unlink(missing_ok=True)
        raise
    return redirect(url_for("matafuegos_real.detail", branch=branch))


def _completion_ready(visit, items):
    _editable(visit)
    if not items:
        raise ValidationError("La sucursal no tiene inventario de matafuegos para relevar.")
    results = visit.get("resultados") or {}
    missing = [item.get("id") for item in items if item.get("id") not in results]
    if missing:
        raise ValidationError("Debe revisar cada matafuego del inventario antes de finalizar.")


@real_bp.post("/proveedor/matafuegos/sucursal/<branch>/finalizar")
@real_required
def complete(branch):
    invalid = _csrf_required()
    if invalid:
        return invalid
    branch, _, error = _authorized_branch(branch)
    if error:
        return error
    data, visit = _provider_visit(branch)
    created = []
    try:
        _completion_ready(visit, _inventory_items(branch))
        remito = _prepare_upload(request.files.get("remito"), "remito", DOCUMENT_EXTENSIONS)
        certificate = _prepare_upload(request.files.get("certificado"), "certificado", DOCUMENT_EXTENSIONS)
        extras = [_prepare_upload(storage, "documento", DOCUMENT_EXTENSIONS) for storage in request.files.getlist("documentos") if storage and storage.filename]
        existing_documents = visit.get("documentos") or {}
        if not remito and not existing_documents.get("remito"):
            raise ValidationError("El remito es obligatorio para finalizar.")
        if not certificate and not existing_documents.get("certificado"):
            raise ValidationError("El certificado es obligatorio para finalizar.")
        uploads = [upload for upload in [remito, certificate, *extras] if upload]
        created = _persist_uploads(visit["id"], uploads) if uploads else []
        documents = copy.deepcopy(existing_documents)
        if remito:
            documents["remito"] = _metadata(remito)
        if certificate:
            documents["certificado"] = _metadata(certificate)
        documents.setdefault("otros", []).extend(_metadata(upload) for upload in extras if upload)
        visit.update(documentos=documents, estado="Realizado", actualizado=_now())
        visit.setdefault("historial", []).append(_history("Visita enviada a validación", "Remito y certificado adjuntos"))
        _save_visits(data)
        flash("Visita enviada a validación administrativa.")
    except ValidationError as exc:
        for path in created:
            path.unlink(missing_ok=True)
        flash(str(exc))
    except Exception:
        for path in created:
            path.unlink(missing_ok=True)
        raise
    return redirect(url_for("matafuegos_real.detail", branch=branch))


@real_bp.get("/admin/proveedores/matafuegos")
@admin_required
def admin_panel():
    visits = _load_visits()
    branches = []
    for branch, owners in sorted(_admin_portfolio().items()):
        items = _inventory_items(branch)
        branches.append((_branch_summary(branch, items), owners, _latest_visit(branch, data=visits)))
    return render_template("matafuegos_real_panel.html", sucursales=branches, is_admin=True)


@real_bp.get("/admin/proveedores/matafuegos/sucursal/<branch>")
@admin_required
def admin_detail(branch):
    branch, owners, error = _authorized_branch(branch, admin=True)
    if error:
        return error
    visit = _latest_visit(branch)
    return _view(branch, owners, visit, admin=True)


def _apply_validation(visit):
    inventory = _load_inventory()
    by_id = {str(item.get("id")): item for item in inventory.get("matafuegos", []) if _branch_num(item.get("sucursal_num") or item.get("sucursal")) == visit.get("sucursal_num")}
    results = visit.get("resultados") or {}
    if set(by_id) != set(results):
        raise ValidationError("El inventario cambió desde el relevamiento; devolvé la visita para revisarlo.")
    for item_id, result in results.items():
        item = by_id[item_id]
        previous_recharge = item.get("fecha_carga", "")
        previous_expiry = item.get("fecha_vencimiento_manual") or item.get("fecha_vencimiento", "")
        event = {
            "fecha": _now(), "autor": _actor(), "origen": "portal_proveedor_matafuegos",
            "visita_id": visit["id"], "proveedor": visit.get("proveedor", ""),
            "fecha_carga_anterior": previous_recharge, "vencimiento_anterior": previous_expiry,
            "fecha_carga": result["fecha_recarga"], "proxima_recarga": result["proximo_vencimiento"],
            "encontrado": result["encontrado"], "estado_fisico": result["estado_fisico"],
            "trabajo_realizado": result["trabajo_realizado"], "observacion": result.get("observacion", ""),
        }
        item.setdefault("historial_mantenimientos", []).append(event)
        item.update({
            "encontrado": result["encontrado"], "estado_fisico": result["estado_fisico"],
            "trabajo_realizado": result["trabajo_realizado"], "fecha_carga": result["fecha_recarga"],
            "fecha_vencimiento_manual": result["proximo_vencimiento"], "nro_extintor": result["identificacion"],
            "ubicacion": result["ubicacion"], "observacion_mantenimiento": result.get("observacion", ""),
            "actualizado_por_proveedor": visit.get("proveedor", ""), "actualizado_at": _now(),
        })
    _save_inventory(inventory)


def _admin_transition(branch, validate):
    invalid = _csrf_required()
    if invalid:
        return invalid
    branch, _, error = _authorized_branch(branch, admin=True)
    if error:
        return error
    data = _load_visits()
    visit = _latest_visit(branch, data=data)
    if not visit:
        return render_template("error.html", mensaje="Visita no encontrada."), 404
    try:
        if visit.get("estado") != "Realizado":
            raise ValidationError("Sólo una visita Realizada puede revisarse.")
        if validate:
            _apply_validation(visit)
            visit.update(estado="Validado", observacion_devolucion="", actualizado=_now())
            visit.setdefault("historial", []).append(_history("Visita validada", "Inventario actualizado"))
            message = "Visita validada e inventario actualizado."
        else:
            observation = _clean(request.form.get("observacion"), "Observación de devolución", required=True, max_length=1000)
            visit.update(estado="Devuelto", observacion_devolucion=observation, actualizado=_now())
            visit.setdefault("historial", []).append(_history("Visita devuelta", observation))
            message = "Visita devuelta para corrección."
        _save_visits(data)
        flash(message)
    except ValidationError as exc:
        flash(str(exc))
    return redirect(url_for("matafuegos_real.admin_detail", branch=branch))


@real_bp.post("/admin/proveedores/matafuegos/sucursal/<branch>/validar")
@admin_required
def validate(branch):
    return _admin_transition(branch, True)


@real_bp.post("/admin/proveedores/matafuegos/sucursal/<branch>/devolver")
@admin_required
def return_for_changes(branch):
    return _admin_transition(branch, False)


@real_bp.get("/proveedor/matafuegos/visita/<visit_id>/archivo/<filename>")
def serve_file(visit_id, filename):
    is_admin = bool(session.get("user") and session.get("rol") == "admin" and _session_valid() and (session.get("auth_provider") != "entra" or session.get("entra_role") == "admin"))
    is_provider = bool(session.get("prov_user") and _session_valid() and _refresh_session() == "matafuegos")
    if not (is_admin or is_provider):
        return render_template("error.html", mensaje="Acceso restringido al archivo."), 403
    data = _load_visits()
    visit = _find_visit(data, visit_id)
    if not visit:
        return render_template("error.html", mensaje="Archivo no encontrado."), 404
    branch, _, error = _authorized_branch(visit.get("sucursal_num"), admin=is_admin)
    if error:
        return error
    if is_provider and visit.get("proveedor_key") != _provider_key():
        return render_template("error.html", mensaje="Acceso restringido al archivo."), 403
    if not _referenced(visit, filename):
        return render_template("error.html", mensaje="Archivo no encontrado."), 404
    return send_from_directory(str(_visit_dir(visit_id)), filename)
