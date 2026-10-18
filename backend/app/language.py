"""Detección de idioma de respaldo.

La fuente preferente del idioma es la interpretación de la IA. Este detector
solo se usa cuando la IA no responde o responde mal, para no contestar al
huésped en un idioma que no es el suyo. Es deliberadamente simple: no es un
detector fiable, es un respaldo.
"""

from __future__ import annotations

import re

# Pistas por palabra. Tras el lower(), las voces con acento ya se resuelven
# como español, así que aquí van las formas sin acento (incluidas las de móvil).
_PISTAS_ES = {
    "quiero",
    "puedo",
    "podria",
    "salir",
    "salida",
    "tarde",
    "hasta",
    "gracias",
    "por",
    "para",
    "las",
    "los",
    "una",
    "manana",
    "habitacion",
    "reserva",
    "puede",
    "seria",
    "como",
    "cuando",
    "dia",
    "senor",
    "hola",
    "buenas",
    "favor",
}
_PISTAS_EN = {
    "check",
    "checkout",
    "out",
    "late",
    "please",
    "can",
    "could",
    "want",
    "would",
    "like",
    "my",
    "room",
    "stay",
    "leave",
    "until",
    "tomorrow",
    "thanks",
    "thank",
    "the",
    "at",
    "hello",
    "hi",
    "morning",
}

# Acentos y signos de apertura son señal fuerte de español.
_SIGNOS_ES = set("áéíóúüñ¿¡")

_WORD_RE = re.compile(r"[a-záéíóúüñ]+")


def detect_language(text: str) -> str:
    """Devuelve "es" o "en" a partir del texto del huésped. Empate o duda: "es"."""
    low = (text or "").lower()
    if any(signo in low for signo in _SIGNOS_ES):
        return "es"
    palabras = set(_WORD_RE.findall(low))
    es = len(palabras & _PISTAS_ES)
    en = len(palabras & _PISTAS_EN)
    if en > es:
        return "en"
    return "es"
