from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


from app.database import create_db_and_tables
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


