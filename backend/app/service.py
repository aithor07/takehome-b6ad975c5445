from __future__ import annotations

from typing import Any

from sqlmodel import Session, select

from app.ai_client import AIInvalidOutput, AIResult, AIServiceError, interpret_message
from app.models import (
    Conversation,
    MessageRecord,
    Proposal,
    ProposalStatus,
    TraceRecord,
)
from app.reservations_client import check_availability, get_stay
from app.rules import (
    PolicyContradictionError,
    PolicyNotFoundError,
    resolve_hotel_policy,
)

from app.sessions import AppError, SessionIdentity


#Utilidades

#Hora hh:mm de un instante
def _hhmm(iso: str) -> str:
    return iso[11:16]


def _requested_iso(day: str, hhmm: str) -> str:
    """La fecha la fija la reserva; el visitante solo elige la hora."""
    return f"{day}T{hhmm}:00Z"

def _operation_key(proposal_id: str) -> str:
    # Idempotencia ante el servicio de reservas: estable y valida para el mock.
    return f"appr-{proposal_id}"


def _trace(
    db: Session,
    actor: SessionIdentity,
    conversation: Conversation,
    stay_id: str,
    result: AIResult | None = None,
    detail: dict[str, Any] | None = None,
) -> str:
    """Traza privada del turno: tokens simulados, duracion y X-Request-ID."""
    trace = TraceRecord(
        actor_token=actor.token,
        actor_role=actor.role,
        hotel_id=actor.hotel_id,
        stay_id=stay_id,
        conversation_pk=conversation.id,
        http_request_id=result.request_id if result else None,
        duration_ms=result.duration_ms if result else None,
        prompt_tokens=result.prompt_tokens if result else None,
        completion_tokens=result.completion_tokens if result else None,
        detail=detail or {},
    )
    db.add(trace)
    db.commit()
    db.refresh(trace)
    return trace.id


def _reply(
    db: Session,
    actor: SessionIdentity,
    conversation: Conversation,
    payload: dict[str, Any],
    status: str,
    message: str,
    trace_id: str,
    proposal_id: str | None = None,
) -> dict[str, Any]:
    """Persiste el turno y devuelve exactamente la forma del contrato."""
    body = {
        "event_id": payload["event_id"],
        "conversation_id": payload["conversation_id"],
        "status": status,
        "message": message,
        "proposal_id": proposal_id,
        "trace_id": trace_id,
        "replayed": False,
    }
    db.add(
        MessageRecord(
            event_id=payload["event_id"],
            conversation_pk=conversation.id,
            actor_token=actor.token,
            stay_id=payload["stay_id"],
            text=payload["text"],
            status=status,
            proposal_id=proposal_id,
            trace_id=trace_id,
            response=body,
        )
    )
    db.commit()
    return body



def _load_or_create_conversation(
    db: Session, actor: SessionIdentity, conversation_id: str, stay_id: str
) -> Conversation:
    """La conversacion queda ligada a propietario, hotel y reserva al crearla."""
    conversation = db.exec(
        select(Conversation).where(
            Conversation.owner_token == actor.token,
            Conversation.conversation_id == conversation_id,
        )
    ).first()
    if conversation is None:
        conversation = Conversation(
            conversation_id=conversation_id,
            owner_token=actor.token,
            owner_role=actor.role,
            org_id=actor.org_id,
            hotel_id=actor.hotel_id,
            stay_id=stay_id,
        )
        db.add(conversation)
        db.commit()
        db.refresh(conversation)
    return conversation


#Textos por idiomas

def _msg_pregunta(lang: str) -> str:
    return (
        "What time would you like to check out?"
        if lang == "en"
        else "¿A qué hora te gustaría salir?"
    )


def _msg_actual(lang: str, actual: str) -> str:
    return (
        f"Your current check-out is at {actual}. No change is needed."
        if lang == "en"
        else f"Tu salida actual es a las {actual}. No es necesario ningún cambio."
    )


def _msg_limite(lang: str, limite: str) -> str:
    return (
        f"The latest check-out we can offer is {limite}."
        if lang == "en"
        else f"La salida tardía máxima que puedo ofrecer es a las {limite}."
    )


def _msg_no_disponible(lang: str) -> str:
    return (
        "I cannot offer that time for this booking."
        if lang == "en"
        else "No puedo ofrecer esa hora para tu reserva."
    )


def _msg_revision(lang: str) -> str:
    return (
        "A staff member will review your request."
        if lang == "en"
        else "Revisará tu solicitud una persona del hotel."
    )


def _msg_pendiente(lang: str, hora: str, fee: int) -> str:
    return (
        f"Your request to check out at {hora}, with a fee of {fee} EUR, is awaiting approval."
        if lang == "en"
        else f"La solicitud de salida a las {hora}, con importe de {fee} EUR, está pendiente de aprobación."
    )



#Caso de uso (mensaje del huesped)

async def handle_message(actor: SessionIdentity, payload: dict[str, Any], db: Session) -> dict[str, Any]:
    #Asegurar que el huesped habla de su reserva
    if actor.stay_id != payload["stay_id"]:
        raise AppError(403, "forbidden", "La reserva no pertenece a esta sesion")
    conversation = _load_or_create_conversation(db, actor, payload["conversation_id"], payload["stay_id"])

    #Idempotencia
    previo = db.exec(select(MessageRecord).where(
        MessageRecord.actor_token == actor.token,
        MessageRecord.conversation_pk == conversation.id,
        MessageRecord.event_id == payload["event_id"]
    )).first()

    if previo is not None:
        identico = (previo.stay_id == payload["stay_id"] and previo.text == payload["text"])
        if identico:
            #Replay identico, conservamos identificadores
            respuesta = dict(previo.response)
            respuesta["replayed"] = True
            return respuesta
        #Mismo event_id con otro contenido
        raise AppError(409, "event_conflict", "Ese event_id ya se uso con otro contenido")

    #Historial del dialogo
    historial = [m.text for m in db.exec(select(MessageRecord).where(MessageRecord.conversation_pk == conversation.id).order_by(MessageRecord.created_at)).all()]

    #La IA solo interpreta
    try:
        lectura = await interpret_message(payload["text"], history=historial)
    except (AIServiceError, AIInvalidOutput):
        #Fallo de IA o salida invalida: respuesta util sin cambios y sin 500
        trace_id = _trace(db, actor, conversation, payload["stay_id"], detail={"ai": "unavailable"})
        return _reply(db, actor, conversation, payload, "handoff", _msg_revision("es"), trace_id)
    trace_id = _trace(db, actor, conversation, payload["stay_id"], result=lectura)
    lang = "en" if lectura.language == "en" else "es"

    def cerrado(status: str, texto: str, proposal: Proposal | None = None) -> dict[str, Any]:
        # Cierra el turno siempre por el mismo camino: traza + mensaje persistido.
        return _reply(
            db, actor, conversation, payload, status, texto, trace_id,
            proposal_id=proposal.id if proposal else None,
        )

    # 5. Sin hora reconocida: preguntar y conservar el dialogo.
    if not lectura.requested_time:
        return cerrado("needs_input", _msg_pregunta(lang))

    # 6. Estado vigente de la reserva (fuente de verdad remota).
    stay = await get_stay(payload["stay_id"], token=actor.remote_reservations_token)
    actual = _hhmm(stay.checkout_at)
    pedida = lectura.requested_time
    solicitada_iso = _requested_iso(stay.checkout_at[:10], pedida)

    # 7. Hora igual o anterior a la actual: solo informar, sin propuesta.
    if pedida <= actual:
        return cerrado("information", _msg_actual(lang, actual))

    # 8. Politica documental del hotel de la sesion (nunca del mensaje).
    try:
        policy = resolve_hotel_policy(actor.org_id, actor.hotel_id)
    except (PolicyNotFoundError, PolicyContradictionError):
        return cerrado("handoff", _msg_revision(lang))

    # 9. Por encima del limite del hotel: declinar citando el limite.
    if pedida > policy.late_checkout_limit:
        return cerrado("declined", _msg_limite(lang, policy.late_checkout_limit))

    # 10. Disponibilidad real de la habitacion para esa hora.
    disp = await check_availability(
        payload["stay_id"], solicitada_iso, token=actor.remote_reservations_token
    )
    if not disp.available:
        if disp.reason == "not_later_than_current_checkout":
            return cerrado("information", _msg_actual(lang, actual))
        return cerrado("declined", _msg_no_disponible(lang))

    # 11. Propuesta pendiente de aprobacion. Aqui NO se escribe nada remoto.
    proposal = Proposal(
        conversation_pk=conversation.id,
        stay_id=payload["stay_id"],
        org_id=actor.org_id,
        hotel_id=actor.hotel_id,
        current_checkout_at=stay.checkout_at,
        requested_checkout_at=solicitada_iso,
        fee_eur=policy.fee_eur,
        policy_document_id=policy.document_id,
        policy_version=policy.version,
        evidence=policy.evidence,
        expected_version=stay.version,
        status=ProposalStatus.awaiting_approval.value,
    )
    proposal.operation_key = _operation_key(proposal.id)
    db.add(proposal)
    db.commit()
    db.refresh(proposal)

    return cerrado(
        "awaiting_approval", _msg_pendiente(lang, pedida, policy.fee_eur), proposal
    )

