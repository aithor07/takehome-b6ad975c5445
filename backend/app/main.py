from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict
from typing import Any
from starlette.exceptions import HTTPException as StarletteHTTPException
from contextlib import asynccontextmanager

from app.ai_client import AIInvalidOutput, AIServiceError
from app.database import create_db_and_tables, SessionDep
from app.reservations_client import ReservationServiceError
from app.rules import PolicyContradictionError, PolicyNotFoundError
from app.sessions import AppError, GuestDep, ManagerDep, SessionIdentityDep
from app.service import handle_message, list_proposals, approve_proposal, reject_proposal, reconcile_proposal, get_conversation
import app.models




_PREFIX = "/api/"


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    yield


class ErrorBody(BaseModel):
    code: str
    message: str

class ErrorResponse(BaseModel):
    error: ErrorBody

ERROR_RESPONSES: dict[int, dict] = {
    401: {"model": ErrorResponse, "description": "Token ausente o invalido"},
    403: {"model": ErrorResponse, "description": "Rol o datos fuera de alcance"},
    422: {"model": ErrorResponse, "description": "Campos desconocidos o invalidos"}

}

def _error(status_code: int, code: str, message: str) -> JSONResponse:
    headers = {"WWW-Authenticate": "Bearer"} if status_code == 401 else None
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message}},
        headers=headers
    )





app = FastAPI(
    title="Una salida mas tarde - API",
    description="Backend que interpreta peticiones con IA, valida reglas y gestiona aprobaciones",
    version="0.1.0",
    lifespan=lifespan,
    responses=ERROR_RESPONSES,
    openapi_tags=[
        {"name": "System", "description": "Salud del Servicio"},
        {"name": "Messages", "description": "Mensajes del huesped e interpretacion de la IA"},
        {"name": "Conversations", "description": "Historial y estado (trazas solo para responsable)"},
        {"name": "Proposals", "description": "Propuestas, aprobación y conciliacion"}
    ]
)

#Manejador global para expeciones de tipo AppError
@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    return _error(exc.status_code, exc.code, exc.message)

#Red de seguridad, nada escapa como 500 sin explicacion
@app.exception_handler(AIServiceError)
async def _ai_error(request: Request, exc: AIServiceError):
    return _error(502 if isinstance(exc, AIInvalidOutput) else 503, exc.code, str(exc))

#Manejador global para ReservationServiceError
@app.exception_handler(ReservationServiceError)
async def _reservation_error(request: Request, exc: ReservationServiceError):
    return _error(exc.status_code or 503, exc.error_code or "reservation_error", str(exc))

#Manejador global para PolicyNotFoundError
@app.exception_handler(PolicyNotFoundError)
async def _policy_missing(request: Request, exc: PolicyNotFoundError):
    return _error(404, "policy_not_found", str(exc))

#Manejador global para PolicyContradictionError
@app.exception_handler(PolicyContradictionError)
async def _policy_conflict(request: Request, exc: PolicyContradictionError):
    return _error(409, "policy_contradiction", str(exc))

#Sustituimos los handlers predeterminados de FastAPI
@app.exception_handler(StarletteHTTPException)
async def _http_error(request: Request, exc: StarletteHTTPException):
    return _error(exc.status_code, "http_error", str(exc.detail))

@app.exception_handler(RequestValidationError)
async def _validation_error(request: Request, exc: RequestValidationError):
    campos = ", ".join(str(e.get("loc", "")) for e in exc.errors())
    return _error(422, "validation_error", f"Campos invalidos o desconocidos: {campos}")



# Configuración de CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Permitir todos los orígenes
    allow_methods=["*"],  # Permitir todos los métodos HTTP
    allow_headers=["*"]  # Permitir todos los encabezados
)

# Ruta health para verificar estado del servicio
@app.get("/health", tags=["System"])
def health_check() -> dict[str, str]:
    return {"status": "ok"}


#Contrato exacto que debe seguir un mensaje
class MessageIn(BaseModel):
    model_config = ConfigDict(extra="forbid") #Extra forbid cualquier campo no contemplado

    event_id: str
    conversation_id: str
    stay_id: str
    text: str


#Ruta /api/messages
@app.post(_PREFIX+"messages", tags=["Messages"])
async def post_message(payload: MessageIn, actor: GuestDep, db: SessionDep) -> dict[str, Any]:
    return await handle_message(actor, payload.model_dump(), db)

#Ruta /api/proposals
@app.get(_PREFIX+"proposals", tags=["Proposals"])
def read_proposals(actor: ManagerDep, db: SessionDep) -> dict[str, Any]:
    return list_proposals(actor, db) #Sincrono, no llama a nada remoto

#Ruta /api/proposals/{id}/approve
@app.post(_PREFIX+"proposals/{id}/approve", tags=["Proposals"])
async def approve_proposal_route(id: str, actor: ManagerDep, db: SessionDep, response: Response) -> dict[str, Any]:
    code, body = await approve_proposal(actor, id, db)
    response.status_code = code
    return body

#Ruta /api/proposals/{id}/reject
#Sincrona, no hay llamadas remotas
@app.post(_PREFIX + "proposals/{id}/reject", tags=["Proposals"])
def reject_proposal_route(id: str, actor: ManagerDep, db: SessionDep, response: Response) -> dict[str, Any]:
    code, body = reject_proposal(actor, id, db)
    response.status_code = code
    return body

#Ruta /api/proposals/{id}/reconcile
@app.post(_PREFIX+"proposals/{id}/reconcile", tags=["Proposals"])
async def reconcile_proposal_route(id: str, actor: ManagerDep, db: SessionDep, response: Response) -> dict[str, Any]:
    code, body = await reconcile_proposal(actor, id, db)
    response.status_code = code
    return body


#Ruta /api/conversations/{conversation_id}
#Huesped propietario o manager del hotel, trazas solo para manager
@app.get(_PREFIX+"conversations/{conversation_id}", tags=["Conversations"])
def read_conversation(conversation_id: str, actor: SessionIdentityDep, db: SessionDep) -> dict[str. Any]:
    return get_conversation(actor, conversation_id, db)