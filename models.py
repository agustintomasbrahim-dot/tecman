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
            prioridad=int(d.get('prioridad') or 4),
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
