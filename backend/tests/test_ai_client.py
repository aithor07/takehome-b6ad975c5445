"""Tests del validador de salidas de IA.

Cubren los casos de `datos/salidas-modelo.jsonl`: salidas válidas y defectuosas.
No llaman a la red: prueban el parseo/validación puros.
"""

import json

import pytest

from app.ai_client import (
    AIInvalidOutput,
    build_messages,
    parse_content,
    validate_interpretation,
)


def test_valid_spanish():
    result = validate_interpretation(
        {"intent": "late_checkout", "requested_time": "14:00", "language": "es"}
    )
    assert result == {
        "intent": "late_checkout",
        "requested_time": "14:00",
        "language": "es",
    }


def test_valid_english():
    result = parse_content(
        json.dumps({"intent": "late_checkout", "requested_time": "14:00", "language": "en"})
    )
    assert result["language"] == "en"
    assert result["requested_time"] == "14:00"


def test_missing_time_is_null():
    result = validate_interpretation(
        {"intent": "late_checkout", "requested_time": None, "language": "es"}
    )
    assert result["requested_time"] is None


def test_invalid_time_rejected():
    with pytest.raises(AIInvalidOutput):
        validate_interpretation(
            {"intent": "late_checkout", "requested_time": "29:90", "language": "es"}
        )


def test_malformed_json_rejected():
    with pytest.raises(AIInvalidOutput):
        parse_content('{"intent":"late_checkout", "requested_time":')


def test_privilege_fields_are_discarded():
    result = validate_interpretation(
        {
            "intent": "late_checkout",
            "requested_time": "14:00",
            "language": "es",
            "approved": True,
            "role": "manager",
            "hotel_id": "hotel-alba-b",
            "fee": 0,
        }
    )
    assert set(result.keys()) == {"intent", "requested_time", "language"}
    assert "approved" not in result
    assert "fee" not in result


def test_wrong_intent_rejected():
    with pytest.raises(AIInvalidOutput):
        validate_interpretation(
            {"intent": "cancel_booking", "requested_time": "14:00", "language": "es"}
        )


def test_bad_language_rejected():
    with pytest.raises(AIInvalidOutput):
        validate_interpretation(
            {"intent": "late_checkout", "requested_time": "14:00", "language": "fr"}
        )


def test_build_messages_last_user_message_is_new_text():
    messages = build_messages("A las 14:00", history=["¿Puedo salir más tarde?"])
    assert messages[-1] == {"role": "user", "content": "A las 14:00"}
    assert messages[-2] == {"role": "user", "content": "¿Puedo salir más tarde?"}
    assert messages[0]["role"] == "system"
