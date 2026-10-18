"""Flujo de conciliacion (P08) contra los servicios reales.

Ejecutar con:  pytest -m integration
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.helpers import crear_propuesta, sesion

pytestmark = pytest.mark.integration


def _propuesta(client, proposal_id: str) -> dict[str, Any]:
    propuestas = client.get("/api/proposals", headers=sesion("manager-a")).json()["proposals"]
    return next(p for p in propuestas if p["id"] == proposal_id)


def test_p08_resultado_incierto_y_reconciliacion(client, escenario):
    escenario(reservations="response-lost")
    proposal_id = crear_propuesta(
        client,
        token="guest-a1",
        event_id="evt-p08",
        conversation_id="conv-p08",
        stay_id="STAY-A1",
    )

    # La escritura pierde la respuesta: ni exito ni fallo definitivo.
    aprobacion = client.post(
        f"/api/proposals/{proposal_id}/approve", headers=sesion("manager-a")
    )
    assert aprobacion.status_code == 202, aprobacion.text
    assert aprobacion.json()["status"] == "pending_verification"
    assert aprobacion.json()["receipt"] is None

    # La propuesta queda pendiente, sin recibo, con una clave estable.
    antes = _propuesta(client, proposal_id)
    assert antes["status"] == "pending_verification"
    assert antes["receipt"] is None
    clave = antes["operation_key"]

    # La primera consulta de la operacion falla: sigue pendiente, no hay fallo definitivo.
    primera = client.post(
        f"/api/proposals/{proposal_id}/reconcile", headers=sesion("manager-a")
    )
    assert primera.status_code == 202, primera.text
    assert primera.json()["status"] == "pending_verification"
    assert primera.json()["receipt"] is None

    # Una consulta posterior con recibo concordante completa sin crear otra operacion.
    respuesta = primera
    for _ in range(3):
        respuesta = client.post(
            f"/api/proposals/{proposal_id}/reconcile", headers=sesion("manager-a")
        )
        assert respuesta.status_code in (200, 202), respuesta.text
        if respuesta.status_code == 200:
            break
        assert respuesta.json()["status"] == "pending_verification"

    assert respuesta.status_code == 200, "no se completo tras reconciliar"
    assert respuesta.json()["status"] == "completed"
    recibo = respuesta.json()["receipt"]
    assert recibo["operation_key"] == clave
    assert recibo["stay_id"] == "STAY-A1"

    # Sigue habiendo un solo cambio: la clave no cambio.
    assert _propuesta(client, proposal_id)["operation_key"] == clave

    
def test_p08_variante_transient_503(client, escenario):
    escenario(reservations="transient-503")
    proposal_id = crear_propuesta(
        client,
        token="guest-a1",
        event_id="evt-p08b",
        conversation_id="conv-p08b",
        stay_id="STAY-A1",
    )
    clave = _propuesta(client, proposal_id)["operation_key"]

    # Primer intento: simulated_rejection confirma que NO se escribio.
    primero = client.post(
        f"/api/proposals/{proposal_id}/approve", headers=sesion("manager-a")
    )
    assert primero.status_code == 409, primero.text
    assert primero.json()["status"] == "awaiting_approval"
    assert primero.json()["receipt"] is None

    # Reintento con la misma clave y contenido: ahora si completa.
    segundo = client.post(
        f"/api/proposals/{proposal_id}/approve", headers=sesion("manager-a")
    )
    assert segundo.status_code == 200, segundo.text
    assert segundo.json()["status"] == "completed"
    assert segundo.json()["receipt"]["operation_key"] == clave
