"""Flujos de propuestas contra los servicios reales (P02, P06, P07, P10).

Ejecutar con:  pytest -m integration
"""

from __future__ import annotations

import pytest

from tests.helpers import crear_propuesta, enviar_mensaje, sesion

pytestmark = pytest.mark.integration


def test_p02_camino_completo(client, estado_limpio):
    proposal_id = crear_propuesta(
        client,
        token="guest-a1",
        event_id="evt-p02",
        conversation_id="conv-a1",
        stay_id="STAY-A1",
    )

    # Antes de aprobar: pendiente, sin recibo, con politica y precio correctos.
    propuestas = client.get("/api/proposals", headers=sesion("manager-a")).json()[
        "proposals"
    ]
    propuesta = next(p for p in propuestas if p["id"] == proposal_id)
    assert propuesta["status"] == "awaiting_approval"
    assert propuesta["receipt"] is None
    assert propuesta["fee_eur"] == 25
    assert propuesta["policy_document_id"] == "coral-alba-policy"
    assert propuesta["policy_version"] == 2
    assert propuesta["evidence"]["document_id"] == "coral-alba-policy"

    # Aprobar -> 200 completed con recibo concordante.
    aprobacion = client.post(
        f"/api/proposals/{proposal_id}/approve", headers=sesion("manager-a")
    )
    assert aprobacion.status_code == 200, aprobacion.text
    assert aprobacion.json()["status"] == "completed"
    recibo = aprobacion.json()["receipt"]
    assert recibo["stay_id"] == "STAY-A1"
    assert recibo["checkout_at"] == "2026-11-10T14:00:00Z"

    # Volver a pedir 14:00 tras el cambio: informa, sin propuesta ni segundo importe.
    segunda = enviar_mensaje(
        client,
        token="guest-a1",
        event_id="evt-p02b",
        conversation_id="conv-a1",
        stay_id="STAY-A1",
        text="Quiero salir a las 14:00",
    )
    assert segunda["status"] == "information"
    assert segunda["proposal_id"] is None


def test_p06_aislamiento_y_rol(client, estado_limpio):
    proposal_id = crear_propuesta(
        client,
        token="guest-a1",
        event_id="evt-p06",
        conversation_id="conv-a1",
        stay_id="STAY-A1",
    )

    # manager-b solo ve su hotel: la propuesta de hotel-alba no aparece.
    ajenas = client.get("/api/proposals", headers=sesion("manager-b")).json()[
        "proposals"
    ]
    assert all(p["id"] != proposal_id for p in ajenas)

    # El huesped no puede aprobar -> 403.
    huesped = client.post(
        f"/api/proposals/{proposal_id}/approve", headers=sesion("guest-a1")
    )
    assert huesped.status_code == 403

    # manager-b no puede aprobar una ajena -> 404.
    manager_ajeno = client.post(
        f"/api/proposals/{proposal_id}/approve", headers=sesion("manager-b")
    )
    assert manager_ajeno.status_code == 404

    # La propuesta legitima no se ha consumido: manager-a la aprueba.
    legitima = client.post(
        f"/api/proposals/{proposal_id}/approve", headers=sesion("manager-a")
    )
    assert legitima.status_code == 200


def test_p07_doble_aprobacion_un_solo_cambio(client, estado_limpio):
    proposal_id = crear_propuesta(
        client,
        token="guest-a1",
        event_id="evt-p07",
        conversation_id="conv-a1",
        stay_id="STAY-A1",
    )

    primera = client.post(
        f"/api/proposals/{proposal_id}/approve", headers=sesion("manager-a")
    )
    segunda = client.post(
        f"/api/proposals/{proposal_id}/approve", headers=sesion("manager-a")
    )

    # Ambas 200 y el mismo cambio (la segunda es replay de la completada).
    assert primera.status_code == 200
    assert segunda.status_code == 200
    assert (
        primera.json()["receipt"]["change_id"] == segunda.json()["receipt"]["change_id"]
    )


def test_p10_rechazo_bloquea_aprobacion(client, estado_limpio):
    proposal_id = crear_propuesta(
        client,
        token="guest-a1",
        event_id="evt-p10",
        conversation_id="conv-a1",
        stay_id="STAY-A1",
    )

    rechazo = client.post(
        f"/api/proposals/{proposal_id}/reject", headers=sesion("manager-a")
    )
    assert rechazo.status_code == 200
    assert rechazo.json()["status"] == "rejected"

    # Aprobar una rechazada -> 409 y sin cambios.
    aprobacion = client.post(
        f"/api/proposals/{proposal_id}/approve", headers=sesion("manager-a")
    )
    assert aprobacion.status_code == 409
