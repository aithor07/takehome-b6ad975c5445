from collections.abc import Generator
from sqlmodel import Session, SQLModel, create_engine
from app.config import settings

#Necesario en SQLite cuando se usa con FastAPI y SQLModel para evitar errores de concurrencia
connect_args = {"check_same_thread": False}

engine = create_engine(settings.database_url, connect_args=connect_args)

#Crea las tablas definidas en models.py si no existen
def create_db_and_tables() -> None:
    SQLModel.metadata.create_all(engine)

#Inyecta la sesión de la base de datos en las rutas de FastAPI
def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session