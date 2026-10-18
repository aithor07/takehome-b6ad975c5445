"""Ayudas compartidas por los tests de integracion."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient


def sesion(token: str) -> dict[str, str]:
    """Cabecera de sesion de demostracion (huesped o responsable)."""
    return {"Authorization": f"Bearer {token}"}


def enviar_mensaje(
    client: TestClient,
    *,
    token: str,
    event_id: str,
    conversation_id: str,
    stay_id: str,
    text: str,
) -> dict[str, Any]:
    """Envia un mensaje de huesped y devuelve la respuesta JSON (200)."""
    respuesta = client.post(
        "/api/messages",
        headers=sesion(token),
        json={
            "event_id": event_id,
            "conversation_id": conversation_id,
            "stay_id": stay_id,
            "text": text,
        },
    )
    respuesta.raise_for_status()
    return respuesta.json()


def crear_propuesta(
    client: TestClient,
    *,
    token: str,
    event_id: str,
    conversation_id: str,
    stay_id: str,
    text: str = "Quiero salir a las 14:00",
) -> str:
    """Crea una propuesta por el flujo de mensajes y devuelve su id."""
    cuerpo = enviar_mensaje(
        client,
        token=token,
        event_id=event_id,
        conversation_id=conversation_id,
        stay_id=stay_id,
        text=text,
    )
    assert cuerpo["status"] == "awaiting_approval", cuerpo
    assert cuerpo["proposal_id"], cuerpo
    return cuerpo["proposal_id"]
