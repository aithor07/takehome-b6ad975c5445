"""Fixtures compartidas por los tests.

- Los tests sin marca son unitarios y no tocan la red.
- Los marcados con `@pytest.mark.integration` llaman a los servicios reales:
  necesitan red y el `.env` con claves, y reinician su estado remoto.
  No se ejecutan por defecto. Para lanzarlos:  pytest -m integration
"""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from app import rules
from app.config import WORKFACTORY_USER_AGENT, settings
from app.database import reset_database
from app.main import app
from app.rules import load_documents


def _reset_servicio_reservas(scenario: str) -> None:
    """Reinicia escenario y datos remotos de reservas (control de pruebas)."""
    base = settings.reservations_base_url.rstrip("/")
    respuesta = httpx.post(
        f"{base}/test/reset",
        headers={
            "Authorization": f"Bearer {settings.reservations_tester_token}",
            "User-Agent": WORKFACTORY_USER_AGENT,
            "X-Test-Scenario": scenario,
            "Content-Type": "application/json",
        },
        json={},
        timeout=15.0,
    )
    respuesta.raise_for_status()


def _reset_servicio_ia(scenario: str) -> None:
    """Reinicia los contadores de la IA (rearma el fallo del escenario)."""
    base = settings.llm_base_url.rstrip("/")
    respuesta = httpx.post(
        f"{base}/test/reset",
        headers={
            "Authorization": f"Bearer {settings.llm_tester_token}",
            "User-Agent": WORKFACTORY_USER_AGENT,
            "X-Test-Scenario": scenario,
            "Content-Type": "application/json",
        },
        json={},
        timeout=15.0,
    )
    respuesta.raise_for_status()


@pytest.fixture
def client():
    """Cliente de la app con lifespan (crea las tablas al arrancar)."""
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def estado_limpio(client):
    """Deja la app y el servicio de reservas como al principio del caso.

    El kit exige reiniciar antes de cada caso independiente.
    """
    reset_database()
    _reset_servicio_reservas(settings.reservations_scenario)
    yield


@pytest.fixture
def escenario(client, monkeypatch):
    """Fija el escenario remoto por test y reinicia los servicios bajo ese escenario.

    El reset remoto rearma el fallo del escenario elegido, asi que hay que
    aplicarlo DESPUES de fijarlo: por eso no se apoya en `estado_limpio`.
    """

    def _fijar(reservations: str = "normal", llm: str = "normal") -> None:
        monkeypatch.setattr(settings, "reservations_scenario", reservations)
        monkeypatch.setattr(settings, "llm_scenario", llm)
        reset_database()
        _reset_servicio_reservas(reservations)
        _reset_servicio_ia(llm)

    return _fijar


@pytest.fixture
def corpus(monkeypatch):
    """Corpus documental que ve la app, modificable durante el test.

    Sustituye la lectura desde disco para inyectar variantes (politicas
    contradictorias, subidas de version/importe) sin tocar el fichero real.
    """
    documentos = load_documents()
    monkeypatch.setattr(rules, "load_documents", lambda *args, **kwargs: documentos)
    return documentos
