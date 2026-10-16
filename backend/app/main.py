from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException
from contextlib import asynccontextmanager

from app.ai_client import AIInvalidOutput, AIServiceError
from app.database import create_db_and_tables
from app.reservations_client import ReservationServiceError
from app.rules import PolicyContradictionError, PolicyNotFoundError
from app.sessions import AppError
import app.models


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
    invalida = isinstance(exc, AIInvalidOutput)
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
    allow_credentials=True,
    allow_methods=["*"],  # Permitir todos los métodos HTTP
    allow_headers=["*"],  # Permitir todos los encabezados
)

# Ruta health para verificar estado del servicio
@app.get("/health", tags=["System"])
def health_check() -> dict[str, str]:
    return {"status": "ok"}


