from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.ai_client import AIInvalidOutput, AIResult, AIServiceError, interpret_message
from app.language import detect_language
from app.models import (
    Conversation,
    MessageRecord,
    Proposal,
    ProposalStatus,
    TraceRecord,
)
from app.reservations_client import (
    ReservationConflictError,
    ReservationRejectedError,
    ReservationServiceError,
    ReservationUncertainError,
    apply_change,
    check_availability,
    get_operation,
    get_stay,
)
from app.rules import (
    PolicyContradictionError,
    PolicyNotFoundError,
    resolve_hotel_policy,
)
from app.sessions import AppError, SessionIdentity

# Utilidades


# Hora hh:mm de un instante
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
    try:
        db.commit()
    except IntegrityError:
        # Otra peticion gano la carrera, devolver su resultado
        db.rollback()
        replay = _replay_si_existe(db, actor, conversation, payload)
        if replay is not None:
            return replay
        raise AppError(
            409, "event_conflict", "Ese event_id ya se uso con otro contenido"
        )

    return body


def _replay_si_existe(
    db: Session,
    actor: SessionIdentity,
    conversation: Conversation,
    payload: dict[str, Any],
) -> dict[str, Any] | None:
    """Replay de un turno ya persistido; 409 si el event_id se reusó con otro contenido."""
    previo = db.exec(
        select(MessageRecord).where(
            MessageRecord.actor_token == actor.token,
            MessageRecord.conversation_pk == conversation.id,
            MessageRecord.event_id == payload["event_id"],
        )
    ).first()
    if previo is None:
        return None
    if previo.stay_id == payload["stay_id"] and previo.text == payload["text"]:
        respuesta = dict(previo.response)
        respuesta["replayed"] = True
        return respuesta
    raise AppError(409, "event_conflict", "Ese event_id ya se uso con otro contenido")


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


def _idioma_actual(conversation: Conversation, text: str) -> str:
    """Idioma del turno: el ultimo aprendido de la conversacion o, si no, una estimacion."""
    if conversation.language in ("es", "en"):
        return conversation.language
    return detect_language(text)


# Textos por idiomas


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


# Caso de uso (mensaje del huesped)


async def handle_message(
    actor: SessionIdentity, payload: dict[str, Any], db: Session
) -> dict[str, Any]:
    # Asegurar que el huesped habla de su reserva
    if actor.stay_id != payload["stay_id"]:
        raise AppError(403, "forbidden", "La reserva no pertenece a esta sesion")
    conversation = _load_or_create_conversation(
        db, actor, payload["conversation_id"], payload["stay_id"]
    )

    # Idempotencia
    replay = _replay_si_existe(db, actor, conversation, payload)
    if replay is not None:
        return replay

    # Historial del dialogo
    historial = [
        m.text
        for m in db.exec(
            select(MessageRecord)
            .where(MessageRecord.conversation_pk == conversation.id)
            .order_by(MessageRecord.created_at)
        ).all()
    ]

    # La IA solo interpreta
    try:
        lectura = await interpret_message(payload["text"], history=historial)
    except (AIServiceError, AIInvalidOutput):
        # Fallo de IA o salida invalida: respuesta util sin cambios y sin 500.
        # La IA no dio idioma: reusamos el de la conversacion o lo estimamos.
        lang = _idioma_actual(conversation, payload["text"])
        trace_id = _trace(
            db,
            actor,
            conversation,
            payload["stay_id"],
            detail={"ai": "unavailable", "language": lang},
        )
        return _reply(
            db, actor, conversation, payload, "handoff", _msg_revision(lang), trace_id
        )
    lang = "en" if lectura.language == "en" else "es"
    # Aprendemos el idioma de la conversacion para los turnos en que la IA falle.
    conversation.language = lang
    db.add(conversation)
    db.commit()
    trace_id = _trace(
        db,
        actor,
        conversation,
        payload["stay_id"],
        result=lectura,
        detail={"language": lang},
    )

    def cerrado(
        status: str, texto: str, proposal: Proposal | None = None
    ) -> dict[str, Any]:
        # Cierra el turno siempre por el mismo camino: traza + mensaje persistido.
        return _reply(
            db,
            actor,
            conversation,
            payload,
            status,
            texto,
            trace_id,
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

    return cerrado(
        "awaiting_approval", _msg_pendiente(lang, pedida, policy.fee_eur), proposal
    )


# Helper reutilizable
def _mapa_conversaciones(db: Session, propuestas: list[Proposal]) -> dict[str, str]:
    # La propuesta guarda la pk interna; el cliente necesita el conversation_id publico
    pks = {p.conversation_pk for p in propuestas}
    if not pks:
        return {}
    filas = db.exec(
        select(Conversation.id, Conversation.conversation_id).where(
            Conversation.id.in_(pks)
        )
    ).all()
    return {pk: conversation_id for pk, conversation_id in filas}


def _proposal_payload(
    p: Proposal, conversation_id: str | None = None
) -> dict[str, Any]:
    return {
        "id": p.id,
        "conversation_id": conversation_id,
        "stay_id": p.stay_id,
        "status": p.status,
        "current_checkout_at": p.current_checkout_at,
        "requested_checkout_at": p.requested_checkout_at,
        "fee_eur": p.fee_eur,
        "policy_document_id": p.policy_document_id,
        "policy_version": p.policy_version,
        "evidence": p.evidence,  # {document_id, version, quote}
        "operation_key": p.operation_key,
        "receipt": p.receipt,  # null hasta que esté comprobada
    }


def _marcar_stale(db: Session, proposal: Proposal) -> None:
    # Marca la propuesta como no ejecutable y la persiste
    proposal.status = ProposalStatus.stale.value
    proposal.updated_at = datetime.now(UTC)
    db.add(proposal)
    db.commit()


def list_proposals(actor: SessionIdentity, db: Session) -> dict[str, Any]:
    # ManagerDep en la ruta ya garantiza el check de identidad
    # Solo las propuestas del hotel del responsable autenticado
    propuestas = db.exec(
        select(Proposal)
        .where(Proposal.hotel_id == actor.hotel_id)
        .order_by(Proposal.created_at)
    ).all()

    # El contrato exige la clave "proposals" y la proyeccion de _proposal_payload
    # El Detalle del responsable necesita el conversation_id para pedir las trazas.
    mapa = _mapa_conversaciones(db, propuestas)
    return {
        "proposals": [
            _proposal_payload(p, mapa.get(p.conversation_pk)) for p in propuestas
        ]
    }


def _decision_payload(p: Proposal, message: str) -> dict[str, Any]:
    return {
        "proposal_id": p.id,
        "status": p.status,
        "message": message,
        "receipt": p.receipt,
    }


async def approve_proposal(
    actor: SessionIdentity, proposal_id: str, db: Session
) -> tuple[int, dict[str, Any]]:
    # Comprobar existencia y pertenencia sin revelar ajenas
    proposal = db.get(Proposal, proposal_id)
    if proposal is None or proposal.hotel_id != actor.hotel_id:
        raise AppError(404, "proposal_not_found", "Propuesta no encontrada")

    # Estados no ejecutables
    if proposal.status == ProposalStatus.completed.value:
        return 200, _decision_payload(proposal, "La propuesta ya estaba completada")
    if proposal.status == ProposalStatus.rejected.value:
        return 409, _decision_payload(proposal, "La propuesta fue rechazada")
    if proposal.status == ProposalStatus.processing.value:
        return 409, _decision_payload(proposal, "La propuesta se esta ejecutando")
    if proposal.status == ProposalStatus.stale.value:
        return 409, _decision_payload(proposal, "La propuesta ya no es valida")

    # Revalidacion, los datos pueden haber cambiado desde que se creo
    try:
        stay = await get_stay(proposal.stay_id, token=actor.remote_reservations_token)
        disp = await check_availability(
            proposal.stay_id,
            proposal.requested_checkout_at,
            token=actor.remote_reservations_token,
        )
    except ReservationServiceError:
        raise AppError(
            503, "reservation_unavailable", "No se pudo comprobar la reserva"
        )

    try:
        policy = resolve_hotel_policy(proposal.org_id, proposal.hotel_id)
    except (PolicyNotFoundError, PolicyContradictionError):
        _marcar_stale(db, proposal)
        return 409, _decision_payload(proposal, "La politica del hotel cambio")
    if (
        stay.version != proposal.expected_version
        or not disp.available
        or policy.version != proposal.policy_version
        or policy.fee_eur != proposal.fee_eur
    ):
        _marcar_stale(db, proposal)
        return 409, _decision_payload(
            proposal, "Los datos cambiaron; la propuesta ya no es valida"
        )
    # Marcar antes de escribir
    proposal.status = ProposalStatus.processing.value
    proposal.updated_at = datetime.now(UTC)
    db.add(proposal)
    db.commit()

    # 5. Escribir (misma operation_key y expected_version de la propuesta)
    try:
        receipt = await apply_change(
            proposal.stay_id,
            proposal.requested_checkout_at,
            proposal.expected_version,
            proposal.operation_key,
            manager_token=actor.remote_reservations_token,
        )
    except ReservationRejectedError:
        # 503 simulated_rejection: no se escribio. Se puede reintentar.
        proposal.status = ProposalStatus.awaiting_approval.value
        db.add(proposal)
        db.commit()
        return 409, _decision_payload(
            proposal, "El cambio no se aplicó; puedes reintentar."
        )
    except ReservationUncertainError:
        proposal.status = ProposalStatus.pending_verification.value
        db.add(proposal)
        db.commit()
        return 202, _decision_payload(
            proposal, "Resultado incierto; pendiente de comprobar."
        )
    except ReservationConflictError:
        proposal.status = ProposalStatus.stale.value
        db.add(proposal)
        db.commit()
        return 409, _decision_payload(proposal, "El cambio ya no es posible.")

    # 6. Exito
    proposal.receipt = receipt.to_dict()
    proposal.status = ProposalStatus.completed.value
    proposal.decided_by = actor.token
    proposal.decided_at = datetime.now(UTC)
    proposal.decision = "approve"
    db.add(proposal)
    db.commit()
    return 200, _decision_payload(proposal, "Cambio completado.")


def reject_proposal(
    actor: SessionIdentity, proposal_id: str, db: Session
) -> tuple[int, dict[str, Any]]:
    proposal = db.get(Proposal, proposal_id)
    # Existencia y pertenencia
    if proposal is None or proposal.hotel_id != actor.hotel_id:
        raise AppError(404, "proposal_not_found", "Propuesta no encontrada")

    # Ya rechazada (idempotente mismo 200)
    if proposal.status == ProposalStatus.rejected.value:
        return 200, _decision_payload(proposal, "La propuesta ya estaba rechazada")

    # No rechazable: empezo a ejecutarse o ya termino
    if proposal.status in (
        ProposalStatus.processing.value,
        ProposalStatus.pending_verification.value,
        ProposalStatus.completed.value,
    ):
        return 409, _decision_payload(proposal, "La propuesta ya no se puede rechazar")

    # Rechazar
    proposal.status = ProposalStatus.rejected.value
    proposal.decided_by = actor.token
    proposal.decided_at = datetime.now(UTC)
    proposal.decision = "reject"
    proposal.updated_at = datetime.now(UTC)
    db.add(proposal)
    db.commit()
    return 200, _decision_payload(proposal, "Propuesta rechazada")


def _trace_payload(t: TraceRecord) -> dict[str, Any]:
    return {
        "http_request_id": t.http_request_id,
        "duration_ms": t.duration_ms,
        "prompt_tokens": t.prompt_tokens,
        "completion_tokens": t.completion_tokens,
        "tokens_simulated": t.tokens_simulated,
        "detail": t.detail,
        "created_at": t.created_at.isoformat(),
    }


async def reconcile_proposal(
    actor: SessionIdentity, proposal_id: str, db: Session
) -> tuple[int, dict[str, Any]]:
    # Comprueba una escritura incierta usando la operation_key, nunca crea operacion nueva solo consullta la que ya existre
    proposal = db.get(Proposal, proposal_id)
    if proposal is None or proposal.hotel_id != actor.hotel_id:
        raise AppError(404, "proposal_not_found", "Propuesta no encontrada")

    # Estados definitivos: se devuelve su estado sin ejecutar nada.
    if proposal.status in (
        ProposalStatus.completed.value,
        ProposalStatus.rejected.value,
    ):
        return 200, _decision_payload(
            proposal, "La propuesta ya tiene un estado definitivo"
        )

    # Solo hay algo que reconciliar si la escritura quedo incierta.
    if proposal.status != ProposalStatus.pending_verification.value:
        return 200, _decision_payload(
            proposal, "No hay ninguna operacion que reconciliar"
        )

    try:
        receipt = await get_operation(
            proposal.operation_key, manager_token=actor.remote_reservations_token
        )
    except ReservationUncertainError:
        # No se pudo comprobar: se conserva pending_verification.
        return 202, _decision_payload(
            proposal, "No se pudo comprobar la operacion; sigue pendiente"
        )

    if receipt is None:
        # Un 404 operation_not_found NO es prueba de fallo definitivo.
        return 202, _decision_payload(
            proposal, "La operacion no consta; sigue pendiente de comprobar"
        )

    # Recibo valido: la escritura si ocurrio.
    proposal.receipt = receipt.to_dict()
    proposal.status = ProposalStatus.completed.value
    proposal.decided_by = proposal.decided_by or actor.token
    proposal.decided_at = proposal.decided_at or datetime.now(UTC)
    proposal.updated_at = datetime.now(UTC)
    db.add(proposal)
    db.commit()
    return 200, _decision_payload(proposal, "Cambio confirmado tras reconciliar")


def get_conversation(
    actor: SessionIdentity, conversation_id: str, db: Session
) -> dict[str, Any]:
    # Historial y estado de una conversacion, solo acceden huesped propietario y manager
    candidatas = db.exec(
        select(Conversation).where(Conversation.conversation_id == conversation_id)
    ).all()

    if actor.role == "guest":
        conversation = next(
            (c for c in candidatas if c.owner_token == actor.token), None
        )
    else:
        conversation = next(
            (c for c in candidatas if c.hotel_id == actor.hotel_id), None
        )

    if conversation is None:
        raise AppError(404, "conversation_not_found", "Conversacion no encontrada")

    mensajes = db.exec(
        select(MessageRecord)
        .where(MessageRecord.conversation_pk == conversation.id)
        .order_by(MessageRecord.created_at)
    ).all()
    propuestas = db.exec(
        select(Proposal)
        .where(Proposal.conversation_pk == conversation.id)
        .order_by(Proposal.created_at)
    ).all()

    body: dict[str, Any] = {
        "conversation_id": conversation.conversation_id,
        "stay_id": conversation.stay_id,
        "hotel_id": conversation.hotel_id,
        "language": conversation.language,
        "messages": [
            {
                "event_id": m.event_id,
                # Lo que escribio el huesped: sin esto el historial solo tendria las respuestas
                "text": m.text,
                "status": m.status,
                "message": (m.response or {}).get("message"),
                "proposal_id": m.proposal_id,
                "created_at": m.created_at.isoformat(),
            }
            for m in mensajes
        ],
        "proposals": [
            _proposal_payload(p, conversation.conversation_id) for p in propuestas
        ],
    }

    # Trazas internas solo para manager.
    if actor.role == "manager":
        trazas = db.exec(
            select(TraceRecord)
            .where(TraceRecord.conversation_pk == conversation.id)
            .order_by(TraceRecord.created_at)
        ).all()
        body["traces"] = [_trace_payload(t) for t in trazas]

    return body
