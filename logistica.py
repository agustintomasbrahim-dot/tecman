"""MVP aislado del portal de logística de insumos.

El estado operativo vive en PostgreSQL (una fila JSON bloqueada por transacción) o,
como fallback, en un JSON atómico fuera del repositorio. No lee ni modifica el stock
ni los tickets operativos de Tecman: los pedidos pueden conservar source_ticket_id
para una futura integración controlada.
"""
from __future__ import annotations

import csv
import datetime as dt
import hmac
import io
import json
import os
import threading
import uuid
from copy import deepcopy
from functools import wraps
from pathlib import Path
from typing import Callable

from flask import abort, flash, redirect, render_template, request, send_file, session, url_for
from openpyxl import Workbook, load_workbook


ROLES = {"dabra", "garin", "compras"}
WAVE_STATES = ("preparado", "retirado", "en_distribucion", "entregado")
_STOCK_HEADERS = ("item", "cantidad")
_MAX_STOCK_ROWS = 5000
_JSON_LOCK = threading.RLock()


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _blank_state() -> dict:
    return {"version": 2, "stock": {}, "orders": {}, "waves": {}, "requisitions": {},
            "requisition_counter": 0, "movements": [], "notifications": []}


def _event(actor: str, action: str, detail: str = "") -> dict:
    return {"at": _now(), "actor": actor or "Sistema", "action": action, "detail": detail}


def _truthy(value) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "si", "sí", "on"}


class LogisticsError(ValueError):
    pass


class LogisticsStore:
    """Repositorio transaccional: PostgreSQL con row lock o JSON replace atómico."""

    def __init__(self, json_path: Path, use_db: bool = False, db=None, model=None):
        self.json_path = Path(json_path)
        self.use_db = bool(use_db and db is not None and model is not None)
        self.db = db
        self.model = model

    def read(self) -> dict:
        if self.use_db:
            row = self.model.query.get("portal")
            return deepcopy(row.payload) if row else _blank_state()
        with _JSON_LOCK:
            if not self.json_path.exists():
                return _blank_state()
            try:
                data = json.loads(self.json_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return _blank_state()
            return data if isinstance(data, dict) else _blank_state()

    def mutate(self, fn: Callable[[dict], object]):
        if self.use_db:
            try:
                row = self.model.query.filter_by(id="portal").with_for_update().first()
                if row is None:
                    row = self.model(id="portal", payload=_blank_state())
                    self.db.session.add(row)
                    self.db.session.flush()
                state = deepcopy(row.payload)
                result = fn(state)
                row.payload = state
                self.db.session.commit()
                return result
            except Exception:
                self.db.session.rollback()
                raise
        with _JSON_LOCK:
            state = self.read()
            result = fn(state)
            self.json_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.json_path.with_name(f".{self.json_path.name}.{uuid.uuid4().hex}.tmp")
            tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, self.json_path)
            return result


class LogisticsService:
    def __init__(self, store: LogisticsStore):
        self.store = store

    def state(self) -> dict:
        return self.store.read()

    def sync_ticket_orders(self, tickets: list[dict]) -> int:
        """Incorpora idempotentemente la bandeja compra_no_productiva sin tocar tickets."""
        def mutate(state):
            existing = {str(x.get("source_ticket_id")) for x in state.get("orders", {}).values() if x.get("source_ticket_id") is not None}
            added = 0
            for ticket in tickets:
                ticket_id = ticket.get("id")
                if str(ticket_id) in existing:
                    continue
                raw_qty = str(ticket.get("compra_np_cantidad") or "1")
                digits = "".join(ch for ch in raw_qty if ch.isdigit())
                requested = max(1, int(digits or 1))
                item = str(ticket.get("subcategoria") or ticket.get("descripcion") or "Insumo").strip()[:160]
                order_id = f"ticket-{ticket_id}"
                state.setdefault("orders", {})[order_id] = {
                    "id": order_id, "source_ticket_id": ticket_id, "sucursal": ticket.get("sucursal", ""),
                    "status": "pendiente_validacion", "wave_id": None, "received_at": None,
                    "lines": [{"item": item, "requested": requested, "approved": 0, "reserved": 0, "shortage": 0}],
                    "history": [_event("Sistema", "ticket_importado", "compra_no_productiva")], "notifications": [],
                }
                existing.add(str(ticket_id)); added += 1
            return added
        return self.store.mutate(mutate)

    def create_order(self, sucursal: str, lines: list[dict], actor: str, source_ticket_id=None) -> dict:
        sucursal = str(sucursal or "").strip()
        if not sucursal:
            raise LogisticsError("Sucursal obligatoria")
        normalized = []
        for row in lines:
            item = str(row.get("item") or "").strip()
            try:
                requested = int(row.get("requested", 0))
            except (TypeError, ValueError):
                requested = 0
            if not item or requested <= 0:
                raise LogisticsError("Cada línea requiere item y cantidad positiva")
            normalized.append({"item": item, "requested": requested, "approved": 0, "reserved": 0, "shortage": 0})
        if not normalized:
            raise LogisticsError("Pedido sin líneas")
        order = {
            "id": uuid.uuid4().hex[:12], "source_ticket_id": source_ticket_id,
            "sucursal": sucursal, "status": "pendiente_validacion", "wave_id": None,
            "received_at": None, "lines": normalized,
            "history": [_event(actor, "pedido_creado")], "notifications": [],
        }
        def mutate(state):
            state.setdefault("orders", {})[order["id"]] = order
            return deepcopy(order)
        return self.store.mutate(mutate)

    @staticmethod
    def _reserved_elsewhere(state: dict, item: str, exclude_order: str = "") -> int:
        total = 0
        for oid, order in state.get("orders", {}).items():
            if oid == exclude_order or order.get("stock_deducted_at"):
                continue
            for line in order.get("lines", []):
                if line.get("item") == item:
                    total += int(line.get("reserved", 0) or 0)
        return total

    def approve(self, order_id: str, approvals: dict[str, int], actor: str) -> dict:
        def mutate(state):
            order = state.get("orders", {}).get(order_id)
            if not order or order.get("wave_id"):
                raise LogisticsError("Pedido inexistente o ya incluido en una ola")
            shortages = []
            for line in order.get("lines", []):
                item = line["item"]
                try:
                    approved = int(approvals.get(item, line.get("requested", 0)))
                except (TypeError, ValueError):
                    raise LogisticsError("Cantidad aprobada inválida")
                if approved < 0 or approved > int(line.get("requested", 0) or 0):
                    raise LogisticsError("La cantidad aprobada debe estar entre cero y la solicitada")
                stock = int(state.get("stock", {}).get(item, 0) or 0)
                free = max(0, stock - self._reserved_elsewhere(state, item, order_id))
                reserved = min(approved, free)
                shortage = approved - reserved
                line.update(approved=approved, reserved=reserved, shortage=shortage)
                if shortage:
                    shortages.append({"item": item, "quantity": shortage})
            shortage_text = "; ".join(f"{row['item']}: {row['quantity']}" for row in shortages)
            order["status"] = "con_faltantes" if shortages else "preparado_retiro_garin"
            order["fulfillment_status"] = "reserva_parcial_preparada" if shortages else "preparado_retiro_garin"
            order.setdefault("history", []).append(_event(actor, "cantidades_validadas", shortage_text))
            if shortages:
                signature = json.dumps(sorted((row["item"], row["quantity"]) for row in shortages),
                                       ensure_ascii=False, separators=(",", ":"))
                requisitions = state.setdefault("requisitions", {})
                current = requisitions.get(order.get("requisition_id"))
                if not current or current.get("shortage_signature") != signature:
                    if current and current.get("status") == "pendiente_compras":
                        current["status"] = "reemplazada"
                        current.setdefault("history", []).append(_event(actor, "requisicion_reemplazada"))
                    state["requisition_counter"] = int(state.get("requisition_counter", 0) or 0) + 1
                    req_id = uuid.uuid4().hex[:12]
                    number = f"REQ-{state['requisition_counter']:06d}"
                    current = {
                        "id": req_id, "number": number, "order_id": order_id,
                        "sucursal": order["sucursal"], "lines": deepcopy(shortages),
                        "shortage_signature": signature, "status": "pendiente_compras",
                        "email_status": "pending", "email_attempts": 0,
                        "email_sent_at": None, "email_last_error": "",
                        "created_at": _now(), "history": [_event(actor, "requisicion_creada", shortage_text)],
                    }
                    requisitions[req_id] = current
                    order["requisition_id"] = req_id
                    order["requisition_number"] = number
                    order.setdefault("history", []).append(_event(actor, "requisicion_creada", number))
                text = f"{current['number']} · Faltante para {order['sucursal']}: {shortage_text}"
                existing = next((n for n in state.setdefault("notifications", [])
                                 if n.get("audience") == "compras" and n.get("order_id") == order_id
                                 and not n.get("read")), None)
                if existing:
                    existing.update(at=_now(), text=text)
                    order["notifications"] = [n for n in order.get("notifications", [])
                                              if n.get("id") != existing.get("id")]
                    order.setdefault("notifications", []).append(deepcopy(existing))
                else:
                    notification = {"id": uuid.uuid4().hex, "at": _now(), "audience": "compras",
                                    "order_id": order_id, "text": text, "read": False}
                    state["notifications"].append(notification)
                    order.setdefault("notifications", []).append(deepcopy(notification))
            else:
                current = state.setdefault("requisitions", {}).get(order.get("requisition_id"))
                if current and current.get("status") == "pendiente_compras":
                    current["status"] = "cancelada_sin_faltante"
                    current.setdefault("history", []).append(_event(actor, "requisicion_cancelada_sin_faltante"))
                order["requisition_id"] = None
                order["requisition_number"] = None
            return deepcopy(order)
        return self.store.mutate(mutate)

    def send_requisition_email(self, requisition_id: str, send_callback: Callable[[dict, dict], None],
                               actor: str, retry: bool = False) -> dict:
        """Envía una requisición una sola vez; una falla queda visible y admite reintento explícito."""
        def claim(state):
            requisition = state.setdefault("requisitions", {}).get(requisition_id)
            if not requisition:
                raise LogisticsError("Requisición inexistente")
            email_status = requisition.get("email_status", "pending")
            if email_status == "sent":
                return {"status": "duplicate", "requisition": deepcopy(requisition)}
            if email_status == "sending":
                return {"status": "busy", "requisition": deepcopy(requisition)}
            if int(requisition.get("email_attempts", 0) or 0) > 0 and not retry:
                return {"status": "duplicate", "requisition": deepcopy(requisition)}
            if retry and email_status != "failed":
                return {"status": "duplicate", "requisition": deepcopy(requisition)}
            requisition["email_status"] = "sending"
            requisition["email_attempts"] = int(requisition.get("email_attempts", 0) or 0) + 1
            requisition["email_last_attempt_at"] = _now()
            requisition.setdefault("history", []).append(_event(actor, "email_compras_intento",
                                                                  str(requisition["email_attempts"])))
            order = state.get("orders", {}).get(requisition.get("order_id"))
            return {"status": "claimed", "requisition": deepcopy(requisition), "order": deepcopy(order)}

        claimed = self.store.mutate(claim)
        if claimed["status"] != "claimed":
            return claimed
        try:
            send_callback(claimed["requisition"], claimed["order"])
        except Exception as exc:
            error = str(exc).strip()[:300] or exc.__class__.__name__

            def fail(state):
                requisition = state["requisitions"][requisition_id]
                requisition["email_status"] = "failed"
                requisition["email_last_error"] = error
                requisition.setdefault("history", []).append(_event(actor, "email_compras_fallido", error))
                return {"status": "error", "requisition": deepcopy(requisition), "error": error}
            return self.store.mutate(fail)

        def sent(state):
            requisition = state["requisitions"][requisition_id]
            requisition["email_status"] = "sent"
            requisition["email_sent_at"] = _now()
            requisition["email_last_error"] = ""
            requisition.setdefault("history", []).append(_event(actor, "email_compras_enviado"))
            return {"status": "sent", "requisition": deepcopy(requisition)}
        return self.store.mutate(sent)

    def import_stock(self, raw: bytes, filename: str, actor: str) -> dict:
        if len(raw) > 2 * 1024 * 1024:
            raise LogisticsError("El archivo excede el máximo de 2 MB")
        suffix = Path(filename or "").suffix.lower()
        try:
            if suffix == ".csv":
                text = raw.decode("utf-8-sig")
                rows = list(csv.DictReader(io.StringIO(text)))
            elif suffix == ".xlsx":
                wb = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
                ws = wb.active
                values = list(ws.iter_rows(values_only=True))
                headers = [str(x or "").strip().lower() for x in (values[0] if values else [])]
                rows = [dict(zip(headers, row)) for row in values[1:]]
            else:
                raise LogisticsError("Formato permitido: CSV o XLSX")
        except (UnicodeDecodeError, csv.Error, OSError, ValueError) as exc:
            raise LogisticsError("Archivo inválido") from exc
        if not rows:
            raise LogisticsError("La importación no contiene filas")
        if len(rows) > _MAX_STOCK_ROWS:
            raise LogisticsError(f"La importación admite hasta {_MAX_STOCK_ROWS} ítems")
        parsed = {}
        for n, row in enumerate(rows, 2):
            item = str(row.get("item") or "").strip()
            try:
                qty = int(row.get("cantidad"))
            except (TypeError, ValueError):
                raise LogisticsError(f"Fila {n}: cantidad inválida")
            if not item or qty < 0 or item in parsed:
                raise LogisticsError(f"Fila {n}: item vacío, duplicado o cantidad negativa")
            parsed[item] = qty
        def mutate(state):
            reserved = {}
            for order in state.get("orders", {}).values():
                if order.get("stock_deducted_at"):
                    continue
                for line in order.get("lines", []):
                    item = line.get("item")
                    reserved[item] = reserved.get(item, 0) + int(line.get("reserved", 0) or 0)
            conflicts = [item for item, qty in reserved.items() if int(parsed.get(item, 0) or 0) < qty]
            if conflicts:
                raise LogisticsError("El stock importado es menor que las reservas activas: " + ", ".join(sorted(conflicts)))
            state["stock"] = parsed
            state.setdefault("notifications", []).append({"id": uuid.uuid4().hex, "at": _now(), "audience": "dabra",
                "text": f"Stock Dabra importado: {len(parsed)} ítems", "read": False})
            return deepcopy(parsed)
        return self.store.mutate(mutate)

    def create_wave(self, order_ids: list[str], cadence: str, actor: str) -> dict:
        if cadence not in {"semanal", "quincenal"}:
            raise LogisticsError("Frecuencia inválida")
        unique_ids = list(dict.fromkeys(str(x) for x in order_ids if x))
        if not unique_ids:
            raise LogisticsError("Seleccioná al menos un pedido")
        def mutate(state):
            orders = []
            for oid in unique_ids:
                order = state.get("orders", {}).get(oid)
                if not order or order.get("wave_id") or not any(int(x.get("reserved", 0) or 0) > 0 for x in order.get("lines", [])):
                    raise LogisticsError("Todos los pedidos deben estar reservados y sin ola")
                orders.append(order)
            wave_id = uuid.uuid4().hex[:12]
            destinations = []
            for order in orders:
                destinations.append({"sucursal": order["sucursal"], "order_id": order["id"],
                    "lines": [{"item": x["item"], "cantidad": int(x.get("reserved", 0) or 0)}
                              for x in order["lines"] if int(x.get("reserved", 0) or 0) > 0]})
            wave = {"id": wave_id, "cadence": cadence, "status": "preparado", "route": "", "observation": "",
                    "order_ids": unique_ids, "destinations": destinations, "stock_deducted_at": None,
                    "history": [_event(actor, "ola_creada", cadence)]}
            state.setdefault("waves", {})[wave_id] = wave
            for order in orders:
                order["wave_id"] = wave_id
                order["status"] = "en_ola"
                order.setdefault("history", []).append(_event(actor, "incluido_en_ola", wave_id))
            return deepcopy(wave)
        return self.store.mutate(mutate)

    def update_wave(self, wave_id: str, status: str, route: str, observation: str, actor: str) -> dict:
        if status not in WAVE_STATES:
            raise LogisticsError("Estado inválido")
        def mutate(state):
            wave = state.get("waves", {}).get(wave_id)
            if not wave:
                raise LogisticsError("Ola inexistente")
            current = wave.get("status", "preparado")
            if WAVE_STATES.index(status) < WAVE_STATES.index(current) or WAVE_STATES.index(status) > WAVE_STATES.index(current) + 1:
                raise LogisticsError("Transición inválida")
            wave["route"] = str(route or "").strip()
            wave["observation"] = str(observation or "").strip()
            if status == "retirado" and not wave.get("stock_deducted_at"):
                required = {}
                for destination in wave.get("destinations", []):
                    for line in destination.get("lines", []):
                        required[line["item"]] = required.get(line["item"], 0) + int(line["cantidad"])
                for item, qty in required.items():
                    if int(state.get("stock", {}).get(item, 0) or 0) < qty:
                        raise LogisticsError(f"Stock insuficiente al retirar: {item}")
                for item, qty in required.items():
                    state["stock"][item] = int(state["stock"][item]) - qty
                    state.setdefault("movements", []).append({"id": f"ola:{wave_id}:{item}", "at": _now(), "actor": actor,
                        "type": "egreso_retiro_garin", "item": item, "quantity": qty, "wave_id": wave_id})
                wave["stock_deducted_at"] = _now()
                for oid in wave.get("order_ids", []):
                    state["orders"][oid]["stock_deducted_at"] = wave["stock_deducted_at"]
            wave["status"] = status
            wave.setdefault("history", []).append(_event(actor, f"estado_{status}", wave.get("route", "")))
            return deepcopy(wave)
        return self.store.mutate(mutate)

    def handoff_to_garin(self, wave_id: str, actor: str) -> dict:
        """Dabra confirma la entrega física a Garín y descuenta stock una sola vez."""
        wave = self.state().get("waves", {}).get(wave_id)
        if not wave:
            raise LogisticsError("Ola inexistente")
        return self.update_wave(wave_id, "retirado", wave.get("route", ""),
                                wave.get("observation", ""), actor)

    def confirm_receipt(self, order_id: str, sucursal: str, actor: str) -> dict:
        def mutate(state):
            order = state.get("orders", {}).get(order_id)
            if not order:
                raise LogisticsError("Pedido inexistente")
            if order.get("sucursal") != sucursal:
                raise PermissionError("Pedido fuera del alcance de la sucursal")
            if order.get("received_at"):
                return deepcopy(order)
            wave = state.get("waves", {}).get(order.get("wave_id"), {})
            if wave.get("status") != "entregado":
                raise LogisticsError("La entrega todavía no figura como entregada")
            order["received_at"] = _now()
            order["status"] = "recibido"
            order.setdefault("history", []).append(_event(actor, "recepcion_confirmada"))
            state.setdefault("notifications", []).append({"id": uuid.uuid4().hex, "at": _now(), "audience": "dabra",
                "order_id": order_id, "text": f"{sucursal} confirmó recepción", "read": False})
            return deepcopy(order)
        return self.store.mutate(mutate)

    def export_wave(self, wave_id: str) -> bytes:
        wave = self.state().get("waves", {}).get(wave_id)
        if not wave:
            raise LogisticsError("Ola inexistente")
        wb = Workbook()
        ws = wb.active
        ws.title = "Distribución"
        ws.append(["Ola", "Frecuencia", "Estado", "Sucursal", "Pedido", "Item", "Cantidad", "Ruta", "Observación"])
        for dest in wave.get("destinations", []):
            for line in dest.get("lines", []):
                ws.append([wave_id, wave.get("cadence"), wave.get("status"), dest.get("sucursal"), dest.get("order_id"),
                           line.get("item"), line.get("cantidad"), wave.get("route"), wave.get("observation")])
        out = io.BytesIO()
        wb.save(out)
        return out.getvalue()

    @staticmethod
    def stock_template() -> bytes:
        wb = Workbook()
        ws = wb.active
        ws.title = "Stock Dabra"
        ws.append(list(_STOCK_HEADERS))
        out = io.BytesIO()
        wb.save(out)
        return out.getvalue()


def _csv_set(name: str) -> set[str]:
    return {x.strip().lower() for x in os.environ.get(name, "").split(",") if x.strip()}


def logistics_entra_role(identity: dict) -> str | None:
    candidates = set()
    claims = identity.get("claims") or {}
    for value in (identity.get("email"), claims.get("preferred_username"), claims.get("email"), claims.get("upn")):
        if value:
            candidates.add(str(value).strip().lower())
    groups = {str(x).strip().lower() for x in (claims.get("groups") or []) if x}
    for role, env_name, group_env in (
        ("dabra", "LOGISTICA_ENTRA_DABRA_EMAILS", "LOGISTICA_ENTRA_DABRA_GROUP_ID"),
        ("garin", "LOGISTICA_ENTRA_GARIN_EMAILS", "LOGISTICA_ENTRA_GARIN_GROUP_ID"),
        ("compras", "LOGISTICA_ENTRA_COMPRAS_EMAILS", "LOGISTICA_ENTRA_COMPRAS_GROUP_ID"),
    ):
        group_id = os.environ.get(group_env, "").strip().lower()
        if candidates & _csv_set(env_name) or (group_id and group_id in groups):
            return role
    return None


def register_logistics(app, service: LogisticsService, csrf_validator: Callable[[], bool],
                       entra_enabled: Callable[[], bool], branch_authorized: Callable[[], bool] | None = None,
                       ticket_loader: Callable[[], list] | None = None,
                       compras_email_sender: Callable[[dict, dict], None] | None = None):
    def actor():
        return session.get("logistica_name") or session.get("logistica_user") or session.get("suc_nombre") or "Sistema"

    def role_required(*roles):
        def decorator(fn):
            @wraps(fn)
            def wrapped(*args, **kwargs):
                if session.get("logistica_role") not in roles:
                    return render_template("error.html", mensaje="Acceso restringido al portal de Logística."), 403
                return fn(*args, **kwargs)
            return wrapped
        return decorator

    def csrf_or_400():
        if not csrf_validator():
            abort(400)

    def branches_enabled():
        return bool(app.config.get("LOGISTICA_INSUMOS_SUCURSALES_ENABLED", False))

    def test_mode():
        return bool(app.config.get("LOGISTICA_PORTAL_TEST_MODE", False))

    @app.route("/logistica/login", methods=["GET", "POST"], endpoint="logistica_login")
    def login():
        if request.method == "POST":
            csrf_or_400()
            users = app.config.get("LOGISTICA_LOCAL_USERS") or {}
            username = request.form.get("usuario", "").strip().lower()
            supplied = request.form.get("password", "")
            entry = users.get(username) or {}
            expected = str(entry.get("password") or "")
            if expected and hmac.compare_digest(supplied, expected) and entry.get("role") in ROLES:
                session.clear(); session.permanent = True
                session.update(logistica_user=username, logistica_name=entry.get("name") or username,
                               logistica_role=entry["role"], auth_provider="local_logistica")
                return redirect(url_for("logistica_garin" if entry["role"] == "garin" else "logistica_panel"))
            flash("Usuario o contraseña incorrectos")
        return render_template("logistica_login.html", entra_enabled=entra_enabled())

    @app.route("/logistica/logout", methods=["POST"], endpoint="logistica_logout")
    def logout():
        csrf_or_400(); session.clear()
        return redirect(url_for("logistica_login"))

    @app.route("/logistica", endpoint="logistica_panel")
    @role_required("dabra", "compras")
    def panel():
        if ticket_loader:
            service.sync_ticket_orders(ticket_loader())
        state = service.state()
        return render_template("logistica_panel.html", state=state, orders=list(state["orders"].values()),
                               waves=list(state["waves"].values()),
                               requisitions=list(state.get("requisitions", {}).values()),
                               role=session.get("logistica_role"))

    @app.route("/logistica/pedidos/<order_id>", methods=["GET", "POST"], endpoint="logistica_order")
    @role_required("dabra")
    def order_detail(order_id):
        state = service.state(); order = state["orders"].get(order_id)
        if not order: abort(404)
        if request.method == "POST":
            csrf_or_400()
            # Usar el orden estable de líneas; no aceptar nombres arbitrarios del request.
            approvals = {line["item"]: request.form.get(f"approved_{idx}", line["requested"]) for idx, line in enumerate(order["lines"])}
            try:
                result = service.approve(order_id, approvals, actor())
                requisition_id = result.get("requisition_id")
                if requisition_id and compras_email_sender:
                    email_result = service.send_requisition_email(requisition_id, compras_email_sender, actor())
                    if email_result["status"] == "error":
                        flash("La requisición quedó creada, pero falló el email a Compras. Podés reintentar sin duplicarla.")
            except LogisticsError as exc: flash(str(exc))
            return redirect(url_for("logistica_order", order_id=order_id))
        requisition = state.setdefault("requisitions", {}).get(order.get("requisition_id"))
        return render_template("logistica_order.html", order=order, stock=state["stock"], requisition=requisition)

    @app.route("/logistica/requisiciones/<requisition_id>/reintentar-email", methods=["POST"],
               endpoint="logistica_requisition_email_retry")
    @role_required("dabra", "compras")
    def requisition_email_retry(requisition_id):
        csrf_or_400()
        if not compras_email_sender:
            abort(503)
        try:
            result = service.send_requisition_email(requisition_id, compras_email_sender, actor(), retry=True)
            if result["status"] == "sent":
                flash("Email a Compras reenviado correctamente")
            elif result["status"] == "error":
                flash("El reintento falló; la requisición sigue pendiente y visible")
            else:
                flash("La requisición no requiere otro envío")
        except LogisticsError as exc:
            flash(str(exc))
        return redirect(request.referrer or url_for("logistica_panel"))

    @app.route("/logistica/stock", methods=["GET", "POST"], endpoint="logistica_stock")
    @role_required("dabra")
    def stock():
        if request.method == "POST":
            csrf_or_400(); upload = request.files.get("archivo")
            if not upload or not upload.filename: abort(400)
            try: service.import_stock(upload.read(), upload.filename, actor()); flash("Stock importado de forma atómica")
            except LogisticsError as exc: flash(str(exc))
            return redirect(url_for("logistica_stock"))
        return render_template("logistica_stock.html", stock=service.state()["stock"])

    @app.route("/logistica/stock/plantilla.xlsx", endpoint="logistica_stock_template")
    @role_required("dabra")
    def stock_template():
        return send_file(io.BytesIO(service.stock_template()), as_attachment=True,
                         download_name="plantilla_stock_dabra.xlsx",
                         mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    @app.route("/logistica/olas", methods=["POST"], endpoint="logistica_wave_create")
    @role_required("dabra")
    def wave_create():
        csrf_or_400()
        try: service.create_wave(request.form.getlist("order_id"), request.form.get("cadence", "semanal"), actor())
        except LogisticsError as exc: flash(str(exc))
        return redirect(url_for("logistica_panel"))

    @app.route("/logistica/demo/pedidos", methods=["POST"], endpoint="logistica_demo_order")
    @role_required("dabra")
    def demo_order():
        if not test_mode():
            abort(404)
        csrf_or_400()
        try:
            service.create_order(request.form.get("sucursal", ""), [{
                "item": request.form.get("item", ""),
                "requested": request.form.get("cantidad", ""),
            }], actor(), source_ticket_id=None)
            flash("Pedido interno de prueba creado")
        except LogisticsError as exc:
            flash(str(exc))
        return redirect(url_for("logistica_panel"))

    @app.route("/logistica/olas/<wave_id>/entregar-garin", methods=["POST"], endpoint="logistica_wave_handoff")
    @role_required("dabra")
    def wave_handoff(wave_id):
        csrf_or_400()
        try:
            service.handoff_to_garin(wave_id, actor())
            flash("Entrega a Garín confirmada; stock descontado")
        except LogisticsError as exc:
            flash(str(exc))
        return redirect(url_for("logistica_panel"))

    @app.route("/logistica/olas/<wave_id>.xlsx", endpoint="logistica_wave_export")
    @role_required("dabra", "garin")
    def wave_export(wave_id):
        try: content = service.export_wave(wave_id)
        except LogisticsError: abort(404)
        return send_file(io.BytesIO(content), as_attachment=True, download_name=f"ola_{wave_id}.xlsx",
                         mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    @app.route("/logistica/garin", endpoint="logistica_garin")
    @role_required("garin")
    def garin():
        return render_template("logistica_garin.html", waves=list(service.state()["waves"].values()))

    @app.route("/logistica/garin/olas/<wave_id>", methods=["POST"], endpoint="logistica_garin_update")
    @role_required("garin")
    def garin_update(wave_id):
        csrf_or_400()
        # Dabra confirma la entrega física y el descuento. Garín sólo organiza
        # la distribución posterior; nunca puede cambiar cantidades ni stock.
        status = request.form.get("status", "")
        if status not in ("en_distribucion", "entregado"):
            flash("Dabra debe confirmar primero la entrega física a Garín")
            return redirect(url_for("logistica_garin"))
        try: service.update_wave(wave_id, status, request.form.get("route", ""),
                                 request.form.get("observation", ""), actor())
        except LogisticsError as exc: flash(str(exc))
        return redirect(url_for("logistica_garin"))

    @app.route("/logistica/sucursal", methods=["GET", "POST"], endpoint="logistica_branch")
    def branch():
        if not branches_enabled(): abort(404)
        if not branch_authorized or not branch_authorized():
            return render_template("error.html", mensaje="Acceso restringido."), 403
        sucursal = session.get("suc_nombre", "")
        if request.method == "POST":
            csrf_or_400()
            # Endpoint extensible para el futuro pedido multi-línea; habilitable sólo por feature flag.
            try: service.create_order(sucursal, [{"item": request.form.get("item"), "requested": request.form.get("cantidad")}], actor())
            except LogisticsError as exc: flash(str(exc))
            return redirect(url_for("logistica_branch"))
        orders = [x for x in service.state()["orders"].values() if x.get("sucursal") == sucursal]
        return render_template("logistica_branch.html", orders=orders, sucursal=sucursal)

    @app.route("/logistica/sucursal/pedidos/<order_id>/recepcion", methods=["POST"], endpoint="logistica_branch_receipt")
    def branch_receipt(order_id):
        if not branches_enabled(): abort(404)
        if not branch_authorized or not branch_authorized():
            return render_template("error.html", mensaje="Acceso restringido."), 403
        csrf_or_400()
        try: service.confirm_receipt(order_id, session.get("suc_nombre", ""), actor())
        except PermissionError: abort(403)
        except LogisticsError as exc: flash(str(exc))
        return redirect(url_for("logistica_branch"))

    app.extensions["logistica_service"] = service
