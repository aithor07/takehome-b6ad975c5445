from __future__ import annotations


from dataclasses import dataclass
from app.config import settings
import json
from pathlib import Path
from typing import Optional, Annotated
from fastapi import Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer



"""
Este archivo gestiona las sesiones e identidades de demostracion
"""


#Ruta por defecto para el archivo de identidades
DEFAULT_IDENTITIES_PATH = Path(__file__).resolve().parent.parent / "data" / "identidades.json"


class AppError(Exception):
    """
    Excepcion de negocio con el formato {"error": {"code": "error_code", "message": "..."}}
    Luego en main @app.exception_handler(AppError) devuelve automaticamente JSON

    """
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message









@dataclass(frozen=True)
class SessionIdentity:
    token: str #Token de sesión (ej: guest-a1, manager-b, etc.)
    role: str #Guest o manager
    org_id: str #ej "org-coral"
    hotel_id: str #ej "hotel-alba"
    stay_id: Optional[str] = None #STAY-A1 para huespedes, None para managers

    
    @property
    def remote_reservations_token(self) -> str:
        token = settings.reservations_token_by_session.get(self.token)

        if not token:
            raise AppError(
                500,
                "missing_remote_token",
                f"No hay clave remota configurada para la sesión '{self.token}'.",

            )
        return token

def load_sessions(path: Path = DEFAULT_IDENTITIES_PATH) -> dict[str, SessionIdentity]:
    #Carga identidades desde el JSON del kit
    raw = json.loads(path.read_text(encoding="utf-8"))
    identities: dict[str, SessionIdentity] = {}
    for item in raw.get("identities", []):
        identity = SessionIdentity(
            token=item["token"],
            role=item["role"],
            org_id=item["org_id"],
            hotel_id=item["hotel_id"],
            stay_id=item.get("stay_id"),
        )
        identities[identity.token] = identity
    return identities


SESSIONS: dict[str, SessionIdentity] = load_sessions()
#Esquema de seguridad estandar de fastapi, bien documentado. auto_error=False para resolver con mis excepciones
bearer_scheme = HTTPBearer(auto_error=False)

def resolve_session_token(token: Optional[str]) -> SessionIdentity:
    #Token -> Identidad. No depende de fastapi
    if not token:
        raise AppError(401, "unauthorized", "Falta el token Bearer o tiene formato invalido")
    session = SESSIONS.get(token)
    if session is None:
        raise AppError(401, "invalid_token", "Sesion no reconocida")
    return session


def get_current_session(credentials: Annotated[Optional[HTTPAuthorizationCredentials], Security(bearer_scheme)]) -> SessionIdentity:
    #HTTPBearer ya quita automaticamente el prefijo Bearer, solo llega el token
    token = credentials.credentials if credentials else None
    return resolve_session_token(token)

#Uso Security(get_current_session) para reutilizar logica de validacion
def require_guest(session: Annotated[SessionIdentity, Security(get_current_session)]) -> SessionIdentity:
    #Exigir que la sesion sea de un huesped
    if session.role != "guest":
        raise AppError(403, "forbidden", "Operación solo permitida para huespedes")
    return session

def require_manager(session: Annotated[SessionIdentity, Security(get_current_session)]) -> SessionIdentity:
    #Exigir sesion de manager
    if session.role != "manager":
        raise AppError(403, "forbidden", "Esta operacion requiere de permisos de manager")
    return session


    


    