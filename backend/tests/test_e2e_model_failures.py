"""Salidas invalidas y fallos de la IA contra los servicios reales (P10).

Ejecutar con:  pytest -m integration
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.helpers import enviar_mensaje, sesion

pytestmark = pytest.mark.integration

_TEXTO = "Quiero salir a las 14:00"


def _proponer(client, event_id: str, conversation_id: str) -> dict[str, Any]:
    return enviar_mensaje(
        client,
        token="guest-a1",
        event_id=event_id,
        conversation_id=conversation_id,
        stay_id="STAY-A1",
        text=_TEXTO,
    )


def _propuestas(client) -> list[dict[str, Any]]:
    return client.get("/api/proposals", headers=sesion("manager-a")).json()["proposals"]


def test_p10_salida_invalida_no_produce_cambios(client, escenario):
    escenario(llm="invalid-time")
    respuesta = _proponer(client, "evt-p10-inv", "conv-p10-inv")
    # Respuesta util (sin 500) y sin propuesta ejecutable.
    assert respuesta["proposal_id"] is None
    assert respuesta["status"] in ("handoff", "needs_input", "declined", "information")
    assert _propuestas(client) == []


def test_p10_json_roto_no_produce_cambios(client, escenario):
    escenario(llm="malformed-json")
    respuesta = _proponer(client, "evt-p10-bad", "conv-p10-bad")
    assert respuesta["proposal_id"] is None
    assert respuesta["status"] in ("handoff", "needs_input", "declined", "information")
    assert _propuestas(client) == []


def test_p10_campos_privilegiados_no_dan_permiso_ni_precio(client, escenario):
    escenario(llm="privilege-fields")
    respuesta = _proponer(client, "evt-p10-priv", "conv-p10-priv")

    # La IA mando approved/role/fee:0/hotel_id ajeno; nada de eso se respeta.
    if respuesta["proposal_id"]:
        propuesta = next(
            p for p in _propuestas(client) if p["id"] == respuesta["proposal_id"]
        )
        assert propuesta["fee_eur"] == 25  # el precio lo fija la politica, no la IA
        assert propuesta["status"] == "awaiting_approval"

    # Ni propuestas ni cambios en el hotel ajeno que la IA intento colar.
    assert (
        client.get("/api/proposals", headers=sesion("manager-b")).json()["proposals"]
        == []
    )


def test_p10_fallo_temporal_de_ia_no_finge_exito(client, escenario):
    escenario(llm="transient-503")
    respuesta = _proponer(client, "evt-p10-503", "conv-p10-503")

    assert respuesta["status"] in ("awaiting_approval", "handoff", "needs_input")
    if respuesta["status"] == "handoff":
        # Reintentos agotados: respuesta util, sin propuesta ni cambio.
        assert respuesta["proposal_id"] is None
        assert _propuestas(client) == []
    else:
        # El reintento funciono: sigue pendiente de aprobacion, sin exito ficticio.
        propuesta = next(
            p for p in _propuestas(client) if p["id"] == respuesta["proposal_id"]
        )
        assert propuesta["status"] == "awaiting_approval"
        assert propuesta["receipt"] is None
