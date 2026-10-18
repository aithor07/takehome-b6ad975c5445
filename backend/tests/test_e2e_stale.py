"""Propuesta obsoleta contra los servicios reales (P09).

Ejecutar con:  pytest -m integration
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.helpers import crear_propuesta, enviar_mensaje, sesion

pytestmark = pytest.mark.integration


def _propuesta(client, proposal_id: str) -> dict[str, Any]:
    propuestas = client.get("/api/proposals", headers=sesion("manager-a")).json()["proposals"]
    return next(p for p in propuestas if p["id"] == proposal_id)


def test_p09_disponibilidad_agotada_al_aprobar(client, escenario):
    escenario(reservations="stale-availability")
    proposal_id = crear_propuesta(
        client,
        token="guest-a1",
        event_id="evt-p09",
        conversation_id="conv-p09",
        stay_id="STAY-A1",
        text="Quiero salir a las 14:00",
    )

    # Entre preparar y aprobar, el servicio cambio: no se escribe.
    aprobacion = client.post(
        f"/api/proposals/{proposal_id}/approve", headers=sesion("manager-a")
    )
    assert aprobacion.status_code == 409
    assert aprobacion.json()["status"] == "stale"
    assert aprobacion.json()["proposal_id"] == proposal_id
    assert aprobacion.json()["receipt"] is None


def test_p09_variante_politica_actualizada(client, estado_limpio, corpus):
    proposal_id = crear_propuesta(
        client,
        token="guest-a1",
        event_id="evt-p09b",
        conversation_id="conv-p09b",
        stay_id="STAY-A1",
        text="Quiero salir a las 14:00",
    )

    # La politica aprobada sube a v3 con otro importe antes de aprobar.
    for documento in corpus:
        if documento.get("document_id") == "coral-alba-policy" and documento.get("version") == 2:
            documento["version"] = 3
            documento["content"] = (
                "Politica aprobada v3. Salida tardia hasta las 14:00 por 30 EUR."
            )
            documento["policy"] = {**documento["policy"], "fee_eur": 30}

    aprobacion = client.post(
        f"/api/proposals/{proposal_id}/approve", headers=sesion("manager-a")
    )
    assert aprobacion.status_code == 409
    assert _propuesta(client, proposal_id)["status"] == "stale"

    # Una nueva propuesta exige otra aprobacion explicita y usa el importe nuevo.
    nueva = enviar_mensaje(
        client,
        token="guest-a1",
        event_id="evt-p09c",
        conversation_id="conv-p09b",
        stay_id="STAY-A1",
        text="Quiero salir a las 14:00",
    )
    assert nueva["status"] == "awaiting_approval"
    assert nueva["proposal_id"] != proposal_id
    assert _propuesta(client, nueva["proposal_id"])["fee_eur"] == 30
