"""Flujos de mensajes contra los servicios reales (P01, P03, duplicados, permisos).

Ejecutar con:  pytest -m integration
"""

from __future__ import annotations

import pytest

from tests.helpers import enviar_mensaje, sesion

pytestmark = pytest.mark.integration


def test_p01_datos_incompletos_y_contexto(client, estado_limpio):
    # Turno 1: sin hora -> needs_input y sin propuesta ejecutable.
    primero = enviar_mensaje(
        client,
        token="guest-a1",
        event_id="evt-p01-1",
        conversation_id="conv-p01",
        stay_id="STAY-A1",
        text="¿Puedo salir más tarde?",
    )
    assert primero["status"] == "needs_input"
    assert primero["proposal_id"] is None

    # Turno 2: interpreta 14:00 y prepara la propuesta pendiente.
    segundo = enviar_mensaje(
        client,
        token="guest-a1",
        event_id="evt-p01-2",
        conversation_id="conv-p01",
        stay_id="STAY-A1",
        text="A las 14:00",
    )
    assert segundo["status"] == "awaiting_approval"
    assert segundo["proposal_id"]

    # Otro huesped no hereda el contexto del primero.
    ajeno = enviar_mensaje(
        client,
        token="guest-a2",
        event_id="evt-p01-3",
        conversation_id="conv-p01",
        stay_id="STAY-A2",
        text="Y a mi?",
    )
    assert ajeno["status"] == "needs_input"
    assert ajeno["proposal_id"] is None


def test_p03_habitacion_sin_disponibilidad(client, estado_limpio):
    # STAY-A2 no admite salida tardia: respuesta util y sin propuesta ejecutable.
    respuesta = enviar_mensaje(
        client,
        token="guest-a2",
        event_id="evt-p03",
        conversation_id="conv-p03",
        stay_id="STAY-A2",
        text="Quiero salir a las 14:00",
    )
    assert respuesta["status"] in ("declined", "handoff")
    assert respuesta["proposal_id"] is None
    # No debe prometer las 14:00.
    assert "14:00" not in respuesta["message"]


def test_duplicado_identico_y_event_conflict(client, estado_limpio):
    primero = enviar_mensaje(
        client,
        token="guest-a1",
        event_id="evt-dup",
        conversation_id="conv-dup",
        stay_id="STAY-A1",
        text="Quiero salir a las 14:00",
    )
    assert primero["status"] == "awaiting_approval"

    # Duplicado identico: conserva identificadores y marca replayed.
    repetido = enviar_mensaje(
        client,
        token="guest-a1",
        event_id="evt-dup",
        conversation_id="conv-dup",
        stay_id="STAY-A1",
        text="Quiero salir a las 14:00",
    )
    assert repetido["replayed"] is True
    assert repetido["proposal_id"] == primero["proposal_id"]
    assert repetido["trace_id"] == primero["trace_id"]

    # Mismo event_id con otro contenido -> 409.
    conflicto = client.post(
        "/api/messages",
        headers=sesion("guest-a1"),
        json={
            "event_id": "evt-dup",
            "conversation_id": "conv-dup",
            "stay_id": "STAY-A1",
            "text": "Quiero salir a las 13:00",
        },
    )
    assert conflicto.status_code == 409


def test_permisos_y_reserva_ajena(client, estado_limpio):
    cuerpo = {
        "event_id": "evt-perm",
        "conversation_id": "conv-perm",
        "stay_id": "STAY-A1",
        "text": "Quiero salir a las 14:00",
    }

    # Sin token -> 401.
    assert client.post("/api/messages", json=cuerpo).status_code == 401

    # Rol de responsable -> 403.
    con_manager = client.post("/api/messages", headers=sesion("manager-a"), json=cuerpo)
    assert con_manager.status_code == 403

    # Reserva ajena -> 403 (sin revelar contenido).
    ajeno = dict(cuerpo, stay_id="STAY-B1")
    assert client.post("/api/messages", headers=sesion("guest-a1"), json=ajeno).status_code == 403

    # Campo no contemplado -> 422.
    con_extra = dict(cuerpo, role="manager")
    assert client.post("/api/messages", headers=sesion("guest-a1"), json=con_extra).status_code == 422
