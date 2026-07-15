import datetime
import uuid
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.dialects.postgresql import JSONB

db = SQLAlchemy()


def _parse_dt(s):
    if not s:
        return None
    try:
        return datetime.datetime.fromisoformat(str(s))
    except (ValueError, TypeError):
        return None


_PRIORIDAD_MAP = {'alta': 1, 'media': 2, 'baja': 3}

def _parse_prioridad(v):
    if v is None:
        return 4
    try:
        return int(v)
    except (ValueError, TypeError):
        return _PRIORIDAD_MAP.get(str(v).lower(), 4)


def _ensure_id(d):
    return str(d['id']) if d.get('id') is not None else uuid.uuid4().hex[:12]


class TicketDB(db.Model):
    __tablename__ = 'tickets'
    id = db.Column(db.String(50), primary_key=True)
    sucursal_num = db.Column(db.String(10), index=True)
    estado = db.Column(db.String(50), index=True)
    prioridad = db.Column(db.Integer, index=True)
    creado = db.Column(db.DateTime)
    payload = db.Column(JSONB, nullable=False)

    @classmethod
    def from_dict(cls, d):
        return cls(
            id=_ensure_id(d),
            sucursal_num=d.get('sucursal_num', ''),
            estado=d.get('estado', ''),
            prioridad=_parse_prioridad(d.get('prioridad')),
            creado=_parse_dt(d.get('creado')),
            payload=d,
        )

    def to_dict(self):
        return self.payload


class MatafuegoDB(db.Model):
    __tablename__ = 'matafuegos'
    id = db.Column(db.String(50), primary_key=True)
    sucursal_num = db.Column(db.String(10), index=True)
    payload = db.Column(JSONB, nullable=False)

    @classmethod
    def from_dict(cls, d):
        return cls(
            id=_ensure_id(d),
            sucursal_num=d.get('sucursal_num', ''),
            payload=d,
        )

    def to_dict(self):
        return self.payload


class HabilitacionDB(db.Model):
    __tablename__ = 'habilitaciones'
    id = db.Column(db.String(50), primary_key=True)
    sucursal_num = db.Column(db.String(10), index=True)
    payload = db.Column(JSONB, nullable=False)

    @classmethod
    def from_dict(cls, d):
        return cls(
            id=_ensure_id(d),
            sucursal_num=d.get('sucursal_num', ''),
            payload=d,
        )

    def to_dict(self):
        return self.payload


class ComprobanteDB(db.Model):
    __tablename__ = 'comprobantes'
    id = db.Column(db.String(50), primary_key=True)
    payload = db.Column(JSONB, nullable=False)

    @classmethod
    def from_dict(cls, d):
        return cls(id=_ensure_id(d), payload=d)

    def to_dict(self):
        return self.payload


class StockMovimientoDB(db.Model):
    __tablename__ = 'stock_movimientos'
    id = db.Column(db.String(50), primary_key=True)
    ticket_id = db.Column(db.String(50), index=True)
    payload = db.Column(JSONB, nullable=False)

    @classmethod
    def from_dict(cls, d):
        return cls(
            id=_ensure_id(d),
            ticket_id=str(d.get('ticket_id', '') or ''),
            payload=d,
        )

    def to_dict(self):
        return self.payload


class NotifAdminDB(db.Model):
    __tablename__ = 'notif_admin'
    id = db.Column(db.String(50), primary_key=True)
    leida = db.Column(db.Boolean, index=True)
    payload = db.Column(JSONB, nullable=False)

    @classmethod
    def from_dict(cls, d):
        return cls(
            id=_ensure_id(d),
            leida=bool(d.get('leida', False)),
            payload=d,
        )

    def to_dict(self):
        return self.payload


class AlertaSyhDB(db.Model):
    __tablename__ = 'alertas_syh'
    id = db.Column(db.String(50), primary_key=True)
    sucursal_num = db.Column(db.String(10), index=True)
    payload = db.Column(JSONB, nullable=False)

    @classmethod
    def from_dict(cls, d):
        return cls(
            id=_ensure_id(d),
            sucursal_num=d.get('sucursal_num', ''),
            payload=d,
        )

    def to_dict(self):
        return self.payload


class SyhGestionDB(db.Model):
    __tablename__ = 'syh_gestiones'
    id = db.Column(db.String(50), primary_key=True)
    sucursal_num = db.Column(db.String(10), index=True)
    estado = db.Column(db.String(50), index=True)
    payload = db.Column(JSONB, nullable=False)

    @classmethod
    def from_dict(cls, d):
        return cls(
            id=_ensure_id(d),
            sucursal_num=d.get('sucursal_num', ''),
            estado=d.get('estado', ''),
            payload=d,
        )

    def to_dict(self):
        return self.payload


class VehiculoDB(db.Model):
    __tablename__ = 'vehiculos_equipo'
    id = db.Column(db.String(50), primary_key=True)
    payload = db.Column(JSONB, nullable=False)

    @classmethod
    def from_dict(cls, d):
        return cls(id=_ensure_id(d), payload=d)

    def to_dict(self):
        return self.payload


class PermisoDB(db.Model):
    __tablename__ = 'permisos'
    id = db.Column(db.String(50), primary_key=True)
    payload = db.Column(JSONB, nullable=False)

    @classmethod
    def from_dict(cls, d):
        return cls(id=_ensure_id(d), payload=d)

    def to_dict(self):
        return self.payload


class PresupuestoDB(db.Model):
    __tablename__ = 'presupuestos'
    id = db.Column(db.String(50), primary_key=True)
    payload = db.Column(JSONB, nullable=False)

    @classmethod
    def from_dict(cls, d):
        return cls(id=_ensure_id(d), payload=d)

    def to_dict(self):
        return self.payload


class CeyhRetiroDB(db.Model):
    __tablename__ = 'ceyh_retiros'
    id = db.Column(db.String(50), primary_key=True)
    payload = db.Column(JSONB, nullable=False)

    @classmethod
    def from_dict(cls, d):
        return cls(id=_ensure_id(d), payload=d)

    def to_dict(self):
        return self.payload


class CeyhJornadaDB(db.Model):
    __tablename__ = 'ceyh_jornadas'
    id = db.Column(db.String(50), primary_key=True)
    payload = db.Column(JSONB, nullable=False)

    @classmethod
    def from_dict(cls, d):
        return cls(id=_ensure_id(d), payload=d)

    def to_dict(self):
        return self.payload


class LoteFifoDB(db.Model):
    __tablename__ = 'lotes_fifo'
    id = db.Column(db.String(50), primary_key=True)
    payload = db.Column(JSONB, nullable=False)

    @classmethod
    def from_dict(cls, d):
        return cls(id=_ensure_id(d), payload=d)

    def to_dict(self):
        return self.payload


class TransferDB(db.Model):
    __tablename__ = 'transfers'
    id = db.Column(db.String(50), primary_key=True)
    payload = db.Column(JSONB, nullable=False)

    @classmethod
    def from_dict(cls, d):
        return cls(id=_ensure_id(d), payload=d)

    def to_dict(self):
        return self.payload


class ConfigDB(db.Model):
    """Clave-valor para documentos JSON únicos (syh, stock, etc.)"""
    __tablename__ = 'config'
    key = db.Column(db.String(100), primary_key=True)
    value = db.Column(JSONB, nullable=False)


class UserDB(db.Model):
    __tablename__ = 'users'

    id = db.Column(db.String(50), primary_key=True, default=lambda: uuid.uuid4().hex)
    email = db.Column(db.String(255), unique=True, index=True)
    username = db.Column(db.String(120), unique=True, index=True)
    first_name = db.Column(db.String(120), nullable=False, default='')
    last_name = db.Column(db.String(120), nullable=False, default='')
    status = db.Column(db.String(20), nullable=False, default='active')
    role = db.Column(db.String(50), nullable=False, default='admin')
    must_change_password = db.Column(db.Boolean, nullable=False, default=False)
    session_version = db.Column(db.Integer, nullable=False, default=1)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    last_login_at = db.Column(db.DateTime)

    @property
    def name(self):
        full_name = f"{self.first_name or ''} {self.last_name or ''}".strip()
        return full_name or self.username or self.email or self.id


class AuthIdentityDB(db.Model):
    __tablename__ = 'auth_identities'
    __table_args__ = (
        db.UniqueConstraint('provider', 'provider_subject', name='uq_auth_provider_subject'),
    )

    id = db.Column(db.String(50), primary_key=True, default=lambda: uuid.uuid4().hex)
    user_id = db.Column(db.String(50), db.ForeignKey('users.id'), nullable=False, index=True)
    provider = db.Column(db.String(50), nullable=False, index=True)
    provider_subject = db.Column(db.String(255), nullable=False, index=True)
    tenant_id = db.Column(db.String(120), index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow)
    last_login_at = db.Column(db.DateTime)


class LocalCredentialDB(db.Model):
    __tablename__ = 'local_credentials'

    user_id = db.Column(db.String(50), db.ForeignKey('users.id'), primary_key=True)
    password_hash = db.Column(db.String(255), nullable=False)
    failed_attempts = db.Column(db.Integer, nullable=False, default=0)
    locked_until = db.Column(db.DateTime)
    password_changed_at = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow)


class PasswordResetTokenDB(db.Model):
    __tablename__ = 'password_reset_tokens'

    id = db.Column(db.String(50), primary_key=True, default=lambda: uuid.uuid4().hex)
    user_id = db.Column(db.String(50), db.ForeignKey('users.id'), nullable=False, index=True)
    token_hash = db.Column(db.String(64), unique=True, nullable=False, index=True)
    expires_at = db.Column(db.DateTime, nullable=False)
    used_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow)


class AuthAuditEventDB(db.Model):
    __tablename__ = 'auth_audit_events'

    id = db.Column(db.String(50), primary_key=True, default=lambda: uuid.uuid4().hex)
    user_id = db.Column(db.String(50), db.ForeignKey('users.id'), index=True)
    event_type = db.Column(db.String(80), nullable=False, index=True)
    provider = db.Column(db.String(50), index=True)
    ip_address = db.Column(db.String(80))
    user_agent = db.Column(db.String(255))
    details = db.Column(JSONB, nullable=False, default=dict)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow, index=True)
