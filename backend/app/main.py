from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware


from app.database import create_db_and_tables
from app.sessions import AppError
import app.models #Para que SQLModel registre las tablas

@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    yield

app = FastAPI(
    title="Una salida mas tarde - API",
    description="Backend que interpreta peticiones con IA, valida reglas y gestiona aprobaciones",
    version="0.1.0",
    lifespan=lifespan
)

#Manejador global para expeciones de tipo AppError
@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    #401 añadimos WWW-Authenticate: Bearer
    headers = {"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": exc.message}},
        headers=headers
    )



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
def health_check():
    return {"status": "ok"}


