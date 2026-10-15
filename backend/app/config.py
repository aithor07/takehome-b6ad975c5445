"""Configuración del servidor leída del entorno (`.env`).

Ninguna de estas claves debe llegar al navegador, a la IA ni a Git.
El hotel/organización salen de la clave remota, nunca del cuerpo de la petición.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

# Identificador exigido por los servicios de WorkFactory (evita el 403 de Cloudflare).
WORKFACTORY_USER_AGENT = "WorkFactory-Technical-Test/1.0"


class Settings(BaseSettings):
    # --- Servicio de reservas ---
    reservations_base_url: str
    reservations_scenario: str = "normal"
    reservations_guest_a1_token: str
    reservations_guest_a2_token: str
    reservations_guest_b1_token: str
    reservations_manager_a_token: str
    reservations_manager_b_token: str
    reservations_tester_token: str

    # --- IA simulada ---
    llm_base_url: str
    llm_model: str = "wf-late-checkout-mock-v1"
    llm_scenario: str = "normal"
    llm_api_key: str
    llm_tester_token: str

    # --- Aplicación ---
    database_url: str = "sqlite:///./app.db"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ------------------------------------------------------------------
    # Mapeo de sesiones de demostración -> clave remota fija.
    # El backend resuelve la sesión y elige la clave; el visitante y la IA
    # nunca pueden elegir clave, hotel, rol ni escenario.
    # ------------------------------------------------------------------
    @property
    def reservations_token_by_session(self) -> dict[str, str]:
        return {
            "guest-a1": self.reservations_guest_a1_token,
            "guest-a2": self.reservations_guest_a2_token,
            "guest-b1": self.reservations_guest_b1_token,
            "manager-a": self.reservations_manager_a_token,
            "manager-b": self.reservations_manager_b_token,
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
