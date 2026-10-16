"""Tests del validador de salidas de IA y de la política de reintentos.

Cubren los casos de `datos/salidas-modelo.jsonl` (salidas válidas y defectuosas)
y el reintento limitado con tenacity. No llaman a la red real: el parseo y la
validación son puros, y los reintentos usan `httpx.MockTransport`.
"""

import json

import httpx
import pytest

from app import ai_client
from app.ai_client import (
    AIInvalidOutput,
    AIServiceError,
    build_messages,
    interpret_message,
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


# --- Reintentos con tenacity (httpx.MockTransport, sin red real) -----------


def _ok_response(request_id: str = "req-1") -> httpx.Response:
    content = json.dumps(
        {"intent": "late_checkout", "requested_time": "14:00", "language": "es"}
    )
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": content}}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 4},
        },
        headers={"X-Request-ID": request_id},
    )


@pytest.fixture
def no_wait(monkeypatch):
    # Anula la espera real entre intentos para que los tests sean instantáneos.
    monkeypatch.setattr(ai_client, "_wait", lambda _retry_state: 0.0)


@pytest.mark.asyncio
async def test_retries_temporary_status_then_succeeds(no_wait):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503, headers={"Retry-After": "0"})
        return _ok_response()

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await interpret_message("Quiero salir a las 14:00", client=client)

    assert calls["n"] == 3
    assert result.intent == "late_checkout"
    assert result.requested_time == "14:00"
    assert result.request_id == "req-1"
    assert result.prompt_tokens == 3


@pytest.mark.asyncio
async def test_retry_exhausted_raises_ai_service_error(no_wait):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(503)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(AIServiceError) as exc:
            await interpret_message("hola", client=client, max_attempts=3)

    # reraise=True: propaga AIServiceError, no el RetryError de tenacity.
    assert not isinstance(exc.value, AIInvalidOutput)
    assert exc.value.retryable is True
    assert calls["n"] == 3


@pytest.mark.asyncio
async def test_invalid_output_is_not_retried(no_wait):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "esto no es json"}}]}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(AIInvalidOutput):
            await interpret_message("hola", client=client)

    # Una salida inválida no se arregla repitiendo: una sola llamada.
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_network_error_is_retried(no_wait):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("fallo de red")
        return _ok_response()

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await interpret_message("hola", client=client)

    assert calls["n"] == 2
    assert result.intent == "late_checkout"


@pytest.mark.asyncio
async def test_non_retryable_status_is_not_retried(no_wait):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(401)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(AIServiceError) as exc:
            await interpret_message("hola", client=client)

    assert exc.value.retryable is False
    assert calls["n"] == 1


# --- Espera entre reintentos (_wait) ---------------------------------------


class _OutcomeStub:
    def __init__(self, exc):
        self._exc = exc

    def exception(self):
        return self._exc


class _RetryStateStub:
    def __init__(self, attempt_number, exc):
        self.attempt_number = attempt_number
        self.outcome = _OutcomeStub(exc)


def test_wait_honours_retry_after():
    state = _RetryStateStub(1, AIServiceError("x", retry_after=1.0))
    assert ai_client._wait(state) == 1.0


def test_wait_caps_retry_after_at_max():
    state = _RetryStateStub(1, AIServiceError("x", retry_after=99.0))
    assert ai_client._wait(state) == ai_client._MAX_WAIT


def test_wait_falls_back_to_exponential_backoff():
    state = _RetryStateStub(1, AIServiceError("x"))
    assert ai_client._wait(state) == 0.5


def test_wait_tolerates_foreign_exception():
    # Un error sin atributo retry_after no debe romper la espera.
    state = _RetryStateStub(2, RuntimeError("sin retry_after"))
    assert ai_client._wait(state) == 1.0
