"""Detección de idioma de respaldo y su uso en la conversación (sin red)."""

from __future__ import annotations

from app.language import detect_language
from app.models import Conversation
from app.service import _idioma_actual


def _conversacion(language: str | None) -> Conversation:
    return Conversation(
        conversation_id="conv",
        owner_token="guest-a1",
        owner_role="guest",
        org_id="org-coral",
        hotel_id="hotel-alba",
        stay_id="STAY-A1",
        language=language,
    )


def test_detecta_espanol():
    assert detect_language("¿Puedo salir más tarde?") == "es"
    assert detect_language("Quiero salir a las 14:00") == "es"


def test_detecta_ingles():
    assert detect_language("Can I check out late tomorrow?") == "en"
    assert detect_language("I want to leave the room at 14:00") == "en"


def test_sin_pistas_o_empate_cae_a_espanol():
    assert detect_language("14:00") == "es"
    assert detect_language("") == "es"


def test_recuerda_el_idioma_aprendido():
    # Aunque el texto del turno sea ambiguo, manda el idioma ya aprendido.
    assert _idioma_actual(_conversacion("en"), "14:00") == "en"
    assert _idioma_actual(_conversacion("es"), "14:00") == "es"


def test_sin_idioma_previo_estima_del_texto():
    assert _idioma_actual(_conversacion(None), "Can I check out late?") == "en"
    assert _idioma_actual(_conversacion(None), "Quiero salir tarde") == "es"
