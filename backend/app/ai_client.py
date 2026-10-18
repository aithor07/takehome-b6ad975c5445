"""Cliente de la IA simulada de WorkFactory.

Contrato: `POST {LLM_BASE_URL}/chat/completions`.

El campo `choices[0].message.content` es **texto que contiene otro JSON**. El
backend lo parsea y valida: solo tres campos (`intent`, `requested_time`,
`language`). Cualquier otro campo (por ejemplo `approved`, `role`, `fee`) se
descarta explícitamente: la IA no concede permisos, precio ni aprobación.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import httpx
from tenacity import (
    AsyncRetrying,
    RetryCallState,
    retry_if_exception,
    stop_after_attempt,
)

from app.config import WORKFACTORY_USER_AGENT, settings

# Validación de la interpretación

VALID_INTENT = "late_checkout"
VALID_LANGUAGES = {"es", "en"}
_TIME_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")

# Códigos que merecen reintento limitado (fallo temporal).
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}

# Tope en segundos para la espera entre reintentos.
_MAX_WAIT = 5.0


class AIServiceError(Exception):
    """Fallo temporal o de transporte al llamar a la IA (reintentable)."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "ai_unavailable",
        retryable: bool = True,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable  # tenacity solo reintenta si sigue en True
        self.retry_after = retry_after  # segundos del header Retry-After


class AIInvalidOutput(AIServiceError):
    """La IA respondió algo inutilizable (no reintentable: hay que validar)."""

    def __init__(self, message, *, code="ai_invalid_output") -> None:
        # No reintentable: repetir la llamada no arregla una salida inválida.
        super().__init__(message, code=code, retryable=False)


def _retry_after_seconds(response: httpx.Response) -> float | None:
    # Lee Retry-After en segundos; None si no viene o no es numérica.
    raw = response.headers.get("Retry-After")
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        return None


def _is_retryable(exc: BaseException) -> bool:
    # Predicado de tenacity: solo reintenta errores propios marcados como retryable.
    # AIInvalidOutput hereda de AIServiceError pero queda fuera (retryable=False).
    return isinstance(exc, AIServiceError) and exc.retryable


def _wait(retry_state: RetryCallState) -> float:
    # Espera entre intentos: respeta Retry-After si viene; si no, backoff exponencial.
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    retry_after = getattr(exc, "retry_after", None)
    if retry_after is not None:
        return min(float(retry_after), _MAX_WAIT)
    return min(0.5 * (2 ** (retry_state.attempt_number - 1)), 4.0)


@dataclass
class AIResult:
    """Resultado válido de una interpretación."""

    intent: str
    requested_time: str | None
    language: str
    request_id: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    duration_ms: int = 0


def validate_interpretation(raw: Any) -> dict[str, Any]:
    """Valida los tres campos permitidos y descarta el resto.

    Devuelve un dict con únicamente `intent`, `requested_time` y `language`.
    """
    if not isinstance(raw, dict):
        raise AIInvalidOutput("La interpretación no es un objeto JSON.")

    if raw.get("intent") != VALID_INTENT:
        raise AIInvalidOutput("Intención no reconocida.")

    # El campo es opcional: si viene, tiene que ser una hora con formato valido.
    requested_time = raw.get("requested_time")
    if requested_time is not None and (
        not isinstance(requested_time, str) or not _TIME_RE.match(requested_time)
    ):
        raise AIInvalidOutput("Hora solicitada inválida.")

    language = raw.get("language")
    if language not in VALID_LANGUAGES:
        raise AIInvalidOutput("Idioma no admitido.")

    # Reconstruimos solo con los campos válidos: se descartan los no permitidos.
    return {
        "intent": VALID_INTENT,
        "requested_time": requested_time,
        "language": language,
    }


def parse_content(content: Any) -> dict[str, Any]:
    """Parsea el texto JSON de la IA y lo valida."""
    if not isinstance(content, str) or not content.strip():
        raise AIInvalidOutput("La IA no devolvió contenido de texto.")
    try:
        obj = json.loads(content)
    except (ValueError, TypeError) as exc:
        raise AIInvalidOutput("La IA devolvió un JSON no válido.") from exc
    return validate_interpretation(obj)


def build_messages(text: str, history: Sequence[str] = ()) -> list[dict[str, str]]:
    """Construye el array `messages`.

    Solo el último mensaje `user` es el que interpreta el mock; conservamos la
    conversación en nuestra base de datos, no dependemos del servicio para el
    contexto.
    """
    messages: list[dict[str, str]] = [
        {
            "role": "system",
            "content": (
                "Clasifica la petición de salida del huésped. Responde solo JSON "
                'con {"intent":"late_checkout","requested_time":"HH:MM"|null,'
                '"language":"es"|"en"}.'
            ),
        }
    ]
    for previous in history:
        messages.append({"role": "user", "content": previous})
    messages.append({"role": "user", "content": text})
    return messages


async def interpret_message(
    text: str,
    *,
    history: Sequence[str] = (),
    scenario: str | None = None,
    client: httpx.AsyncClient | None = None,
    max_attempts: int = 3,
) -> AIResult:
    """Interpreta un mensaje con la IA simulada.

    - Reintento limitado ante errores temporales (503/429/…), respetando
      `Retry-After`.
    - Valida el contenido: un JSON roto o una hora inválida lanzan
      `AIInvalidOutput` (no reintentable, no produce cambios).
    """
    url = f"{settings.llm_base_url.rstrip('/')}/chat/completions"
    payload = {
        "model": settings.llm_model,
        "messages": build_messages(text, history),
    }
    headers = {
        "Authorization": f"Bearer {settings.llm_api_key}",
        "Content-Type": "application/json",
        "User-Agent": WORKFACTORY_USER_AGENT,
        "X-Test-Scenario": scenario or settings.llm_scenario,
    }

    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=10.0)

    async def _attempt() -> AIResult:
        # Un intento completo: llamada HTTP + comprobación de estado + parseo.
        # Los fallos temporales se lanzan como AIServiceError (retryable=True);
        # el parseo/validación lanza AIInvalidOutput (retryable=False) para no reintentar.
        started = time.monotonic()
        try:
            response = await http.post(url, headers=headers, json=payload)
        except httpx.RequestError as exc:
            # Fallo de red: se convierte a error propio para que tenacity lo reintente.
            raise AIServiceError(f"Error de red al llamar a la IA: {exc}") from exc

        duration_ms = int((time.monotonic() - started) * 1000)

        if response.status_code in _RETRYABLE_STATUS:
            # Fallo temporal: reintentable y respetando Retry-After si viene.
            raise AIServiceError(
                f"La IA no está disponible (HTTP {response.status_code}).",
                retry_after=_retry_after_seconds(response),
            )

        if response.status_code != 200:
            # Estado inesperado y no temporal (400/401/403/404...): no se reintenta.
            raise AIServiceError(
                f"Respuesta inesperada de la IA (HTTP {response.status_code}).",
                retryable=False,
            )

        try:
            data = response.json()
            content = data["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise AIInvalidOutput(
                "La IA devolvió una estructura de chat inesperada."
            ) from exc

        interpretation = parse_content(content)
        usage = data.get("usage") or {}
        return AIResult(
            intent=interpretation["intent"],
            requested_time=interpretation["requested_time"],
            language=interpretation["language"],
            request_id=response.headers.get("X-Request-ID"),
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            duration_ms=duration_ms,
        )

    # Bucle de reintento con tenacity en versión async (no bloquea el event loop).
    # reraise=True propaga el AIServiceError original al agotar los intentos;
    # sin reraise lanzaría RetryError y rompería el mapeo de errores.
    retryer = AsyncRetrying(
        stop=stop_after_attempt(max_attempts),
        wait=_wait,
        retry=retry_if_exception(_is_retryable),
        reraise=True,
    )
    try:
        return await retryer(_attempt)
    finally:
        if owns_client:
            await http.aclose()
