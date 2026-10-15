"""
    Cliente asíncrono para el servicio remoto de reservas, gestiona lecturas de estancia
    comprobacion de disponibilidad, escritura de cambios con control de version ('expected_version)
    e idempotencia ('operation_key'), y consulta de recibos
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Optional
import httpx
from app.config import WORKFACTORY_USER_AGENT, settings

class ReservationServiceError(Exception):
    #Error base al comunicarse con el servicio de reservas
    def __init__(self, message: str, *, status_code: Optional[int] = None, error_code: Optional[str] = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code

class ReservationNotFoundError(Exception):
    #La reserva u operacion no existe o es ajena (http 403/404)
    pass

class ReservationConflictError(ReservationServiceError):
    """
    Conflicto de negocio en el servicio remoto (http 409)
    version_conflict: la version de estancia cambio
    checkout_unavailable: ya no hay disponibilidad
    operation_key_conflict: misma clave con distinto payload 
    """
    pass

class ReservationRejectedError(ReservationServiceError):
    """Fallo transitorio confirmado donde el servidor garantiza que NO escribió
    (HTTP 503 con error.code == simulated_rejection).
    """
    pass

class ReservationUncertainError(ReservationServiceError):
    """Corte de red, timeout o fallo al recibir la respuesta de POST /changes.
    No se si el cambio se aplicó: la propuesta debe pasar a pending_verification.
    """
    pass
@dataclass(frozen=True)
class StayInfo:
    stay_id: str
    hotel_id: str
    room: str
    checkout_at: str
    version: int

@dataclass(frozen=True)
class AvailabilityResult:
    available: bool
    reason: Optional[str]
    stay_version: int
    requested_checkout_at: str

@dataclass(frozen=True)
class ChangeReceipt:
    stay_id: str
    checkout_at: str
    version: int
    operation_key: str
    change_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "stay_id": self.stay_id,
            "checkout_at": self.checkout_at,
            "version": self.version,
            "operation_key": self.operation_key,
            "change_id": self.change_id
        }
def _headers(token: str, scenario: Optional[str] = None) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "User-Agent": WORKFACTORY_USER_AGENT,
        "X-Test-Scenario": scenario or settings.reservations_scenario
    }

def _extract_error(response: httpx.Response) -> tuple[Optional[str], str]:
    """Extrae error.code, error.message del cuerpo JSON si existe"""
    try:
        data = response.json()
        if isinstance(data, dict) and isinstance(data.get("error"), dict):
            err = data["error"]
            return err.get("code"), err.get("message") or response.text
    except ValueError:
        pass
    return None, response.text or f"HTTP {response.status_code}"

async def get_stay(stay_id: str, *, token: str, scenario: Optional[str] = None, client: Optional[httpx.AsyncClient] = None) -> StayInfo:
    """Obtiene los datos actuales de una reserva (GET /stays/{stay_id})."""
    url = f"{settings.reservations_base_url.rstrip('/')}/stays/{stay_id}"
    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=10.0)
    try:
        try:
            resp = await http.get(url, headers=_headers(token, scenario))
        except httpx.RequestError as exc:
            raise ReservationServiceError(f"Error de red al consultar estancia {stay_id}: {exc}") from exc

        if resp.status_code in (403, 404):
            code, msg = _extract_error(resp)
            raise ReservationNotFoundError(msg, status_code=resp.status_code, error_code=code)
        if resp.status_code != 200:
            code, msg = _extract_error(resp)
            raise ReservationServiceError(msg, status_code=resp.status_code, error_code=code)
        
        data = resp.json()
        return StayInfo(
            stay_id=str(data["stay_id"]),
            hotel_id=str(data["hotel_id"]),
            room=str(data["room"]),
            checkout_at=str(data["checkout_at"]),
            version=int(data["version"])
        )
    finally:
        if owns_client:
            await http.aclose()

async def check_availability(
    stay_id: str,
    requested_checkout_at: str,
    *,
    token: str,
    scenario: Optional[str] = None,
    client: Optional[httpx.AsyncClient] = None,
) -> AvailabilityResult:
    """Comprueba disponibilidad en el servicio remoto (POST /availability/check)."""
    url = f"{settings.reservations_base_url.rstrip('/')}/availability/check"
    payload = {
        "stay_id": stay_id,
        "requested_checkout_at": requested_checkout_at,
    }
    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=10.0)
    try:
        try:
            resp = await http.post(
                url, headers=_headers(token, scenario), json=payload
            )
        except httpx.RequestError as exc:
            raise ReservationServiceError(
                f"Error de red al comprobar disponibilidad: {exc}"
            ) from exc

        if resp.status_code in (403, 404):
            code, msg = _extract_error(resp)
            raise ReservationNotFoundError(
                msg, status_code=resp.status_code, error_code=code
            )

        if resp.status_code != 200:
            code, msg = _extract_error(resp)
            raise ReservationServiceError(
                msg, status_code=resp.status_code, error_code=code
            )

        data = resp.json()
        return AvailabilityResult(
            available=bool(data["available"]),
            reason=data.get("reason"),
            stay_version=int(data["stay_version"]),
            requested_checkout_at=str(data["requested_checkout_at"]),
        )
    finally:
        if owns_client:
            await http.aclose()


async def apply_change(
    stay_id: str,
    requested_checkout_at: str,
    expected_version: int,
    operation_key: str,
    *,
    manager_token: str,
    scenario: Optional[str] = None,
    client: Optional[httpx.AsyncClient] = None,
) -> ChangeReceipt:
    """Aplica el cambio de salida (POST /changes) usando la clave del manager.

    - Si devuelve 200 o 201 con recibo válido -> ChangeReceipt.
    - Si devuelve 409 -> ReservationConflictError (version_conflict, checkout_unavailable, operation_key_conflict)
    - Si devuelve 503 con simulated_rejection -> ReservationRejectedError. Sabemos 100% que no se aplico
    - Si hay corte de conexión, timeout o respuesta rota/5xx incierto -> ReservationUncertainError (queda en pending_verification).
    """
    if isinstance(expected_version, bool) or not isinstance(expected_version, int) or expected_version < 1:
        raise ValueError("expected_version debe ser un entero positivo.")

    url = f"{settings.reservations_base_url.rstrip('/')}/changes"
    payload = {
        "stay_id": stay_id,
        "requested_checkout_at": requested_checkout_at,
        "expected_version": expected_version,
        "operation_key": operation_key,
    }
    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=10.0)
    try:
        try:
            resp = await http.post(
                url, headers=_headers(manager_token, scenario), json=payload
            )
        except httpx.RequestError as exc:
            raise ReservationUncertainError(
                f"Respuesta perdida o corte de red al aplicar cambio: {exc}"
            ) from exc

        if resp.status_code in (200, 201):
            try:
                data = resp.json()
                return ChangeReceipt(
                    stay_id=str(data["stay_id"]),
                    checkout_at=str(data["checkout_at"]),
                    version=int(data["version"]),
                    operation_key=str(data["operation_key"]),
                    change_id=str(data["change_id"]),
                )
            except (ValueError, KeyError, TypeError) as exc:
                raise ReservationUncertainError(
                    "El servidor respondió 2xx pero el recibo está incompleto o corrupto."
                ) from exc

        code, msg = _extract_error(resp)

        if resp.status_code == 409:
            raise ReservationConflictError(
                msg, status_code=409, error_code=code
            )

        if resp.status_code in (403, 404):
            raise ReservationNotFoundError(
                msg, status_code=resp.status_code, error_code=code
            )

        if resp.status_code == 503 and code == "simulated_rejection":
            raise ReservationRejectedError(
                msg, status_code=503, error_code=code
            )

        # Cualquier otro 5xx o caída durante la escritura es resultado incierto.
        raise ReservationUncertainError(
            msg, status_code=resp.status_code, error_code=code
        )
    finally:
        if owns_client:
            await http.aclose()


async def get_operation(
    operation_key: str,
    *,
    manager_token: str,
    scenario: Optional[str] = None,
    client: Optional[httpx.AsyncClient] = None,
) -> Optional[ChangeReceipt]:
    """Consulta el estado de una operación por su operation_key (GET /operations/{key})

    - Si devuelve 200 con status == "applied" y recibo -> devuelve ChangeReceipt.
    - Si devuelve 404 operation_not_found -> devuelve None (no consta cambio
      aplicado con esa clave).
    - Si falla con 503 u otro error de red -> lanza ReservationUncertainError.
    """
    url = f"{settings.reservations_base_url.rstrip('/')}/operations/{operation_key}"
    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=10.0)
    try:
        try:
            resp = await http.get(
                url, headers=_headers(manager_token, scenario)
            )
        except httpx.RequestError as exc:
            raise ReservationUncertainError(
                f"Error de red al consultar operación {operation_key}: {exc}"
            ) from exc

        if resp.status_code == 200:
            try:
                data = resp.json()
                receipt_data = data.get("receipt") or data
                return ChangeReceipt(
                    stay_id=str(receipt_data["stay_id"]),
                    checkout_at=str(receipt_data["checkout_at"]),
                    version=int(receipt_data["version"]),
                    operation_key=str(receipt_data["operation_key"]),
                    change_id=str(receipt_data["change_id"]),
                )
            except (ValueError, KeyError, TypeError) as exc:
                raise ReservationUncertainError(
                    "Recibo de operación mal formado."
                ) from exc

        code, msg = _extract_error(resp)
        if resp.status_code == 404 and code == "operation_not_found":
            return None

        raise ReservationUncertainError(
            msg, status_code=resp.status_code, error_code=code
        )
    finally:
        if owns_client:
            await http.aclose()