import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from app.config import settings

class AIServiceError(Exception):
    """Error controlado cuando la API simule fallas o devuelva datos inválidos."""
    pass


@retry(
    stop=stop_after_attempt(3), #Detiene despues de 3 intentos
    wait=wait_exponential(multiplier=0.5, min=0.5, max=4), #Cada vez que falle, espera el doble de tiempo, empezando en 0.5s y maximo 4s
    retry=retry_if_exception_type((httpx.RequestError, httpx.HTTPStatusError)),
    reraise=True
)
async def call_simulated_ai(prompt:str) -> dict:
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.post(
            settings.ai_api_url,
            headers={"Authorization": f"Bearer {settings.ai_api_key}"},
            json={"prompt": prompt} #TODO: Ajustar segun la estructura que espera la API simulada
        )
        #Si el error es de los 500s o 429 (rate limiting), lanzamos excepcion para que Tenacity reintente
        if response.status_code in (429, 500, 502, 503, 504):
            response.raise_for_status()

        return response.json()