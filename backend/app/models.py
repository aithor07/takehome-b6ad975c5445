"""Modelos de la base de datos (SQLModel).

Persistimos conversaciones, mensajes, propuestas, aprobaciones, identificadores
de operación y confirmaciones. Reiniciar la app no debe perder trabajo ni repetir
un cambio ya aplicado.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from sqlalchemy import Column, JSON, UniqueConstraint
from sqlmodel import Field, SQLModel


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ProposalStatus(str, Enum):
    """Estados de una propuesta (contrato app-api.md)."""

    awaiting_approval = "awaiting_approval"
    processing = "processing"
    pending_verification = "pending_verification"
    completed = "completed"
    rejected = "rejected"
    stale = "stale"
    failed = "failed"


class MessageStatus(str, Enum):
    """Estados de respuesta de `POST /api/messages`."""

    needs_input = "needs_input"
    information = "information"
    awaiting_approval = "awaiting_approval"
    declined = "declined"
    handoff = "handoff"


class Conversation(SQLModel, table=True):
    """Hilo de conversación ligado a su propietario, hotel y reserva."""

    __tablename__ = "conversations"
    __table_args__ = (
        UniqueConstraint("owner_token", "conversation_id", name="uq_conversation_owner"),
    )

    id: str = Field(default_factory=_uuid, primary_key=True)
    conversation_id: str = Field(index=True)
    owner_token: str = Field(index=True)
    owner_role: str
    org_id: str
    hotel_id: str
    stay_id: str
    # Último idioma conocido de la conversación (para turnos con la IA caída).
    language: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=_now)


class MessageRecord(SQLModel, table=True):
    """Mensaje de huésped y su resultado.

    La clave de deduplicación es `(actor, conversation_id, event_id)`.
    Guardamos la respuesta completa para poder reproducirla tal cual en un
    `replay` idéntico (mismos identificadores, `replayed: true`).
    """

    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint(
            "actor_token", "conversation_pk", "event_id", name="uq_message_dedup"
        ),
    )

    id: str = Field(default_factory=_uuid, primary_key=True)
    event_id: str = Field(index=True)
    conversation_pk: str = Field(foreign_key="conversations.id", index=True)
    actor_token: str = Field(index=True)
    stay_id: str
    text: str
    status: str
    proposal_id: Optional[str] = Field(default=None, index=True)
    trace_id: Optional[str] = None
    # Respuesta serializada para reproducir un duplicado idéntico.
    response: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=_now)


class Proposal(SQLModel, table=True):
    """Propuesta de cambio de salida pendiente de aprobación."""

    __tablename__ = "proposals"

    id: str = Field(default_factory=_uuid, primary_key=True)
    conversation_pk: str = Field(foreign_key="conversations.id", index=True)
    stay_id: str = Field(index=True)
    org_id: str
    hotel_id: str = Field(index=True)

    current_checkout_at: str  # `YYYY-MM-DDTHH:MM:SSZ`
    requested_checkout_at: str
    fee_eur: int

    # Fuente que respalda horario, límite e importe.
    policy_document_id: str
    policy_version: int
    evidence: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))

    # Versión de la reserva contra la que se preparó la propuesta.
    expected_version: int

    # Identificador de operación estable (idempotencia en el servicio remoto).
    operation_key: str = Field(index=True)

    status: str = Field(default=ProposalStatus.awaiting_approval.value, index=True)
    receipt: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSON))

    # Quién y cuándo aprobó/rechazó (auditoría).
    decided_by: Optional[str] = None
    decided_at: Optional[datetime] = None
    decision: Optional[str] = None  # "approve" | "reject"

    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class TraceRecord(SQLModel, table=True):
    """Registro de seguimiento privado: llamadas, duración y tokens simulados.

    Solo se expone al responsable; nunca al huésped.
    """

    __tablename__ = "traces"

    id: str = Field(default_factory=_uuid, primary_key=True)
    actor_token: str = Field(index=True)
    actor_role: str
    hotel_id: str
    stay_id: Optional[str] = None
    conversation_pk: Optional[str] = None
    proposal_id: Optional[str] = None

    http_request_id: Optional[str] = None  # X-Request-ID de la IA
    duration_ms: Optional[int] = None
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    tokens_simulated: bool = True

    detail: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=_now)
