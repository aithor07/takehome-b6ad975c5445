# Una salida más tarde

Aplicación web para gestionar peticiones de salida tardía en un hotel. El huésped
escribe su petición, una IA simulada la interpreta, el servidor comprueba las reglas
del hotel y la disponibilidad, y un responsable aprueba antes de que se modifique la
reserva. La web solo muestra como completado lo que el servicio de reservas ha
confirmado.

Prueba técnica de WorkFactory sobre dos servicios remotos de prueba (reservas e IA
simulada). Los hoteles, reservas y documentos son ficticios.

## Índice

1. [Arquitectura y componentes](#arquitectura-y-componentes)
2. [Estados](#estados)
3. [Conexión a los servicios](#conexión-a-los-servicios)
4. [Puesta en marcha](#puesta-en-marcha)
5. [Base de datos](#base-de-datos)
6. [Pruebas](#pruebas)
7. [Resultados de los casos](#resultados-de-los-casos)
8. [Límites y trabajo futuro](#límites-y-trabajo-futuro)
9. [Tiempo empleado](#tiempo-empleado)
10. [Decisiones](#decisiones)

## Arquitectura y componentes

El proyecto está dividido en dos partes independientes, **frontend** y **backend**,
para poder desplegar cada una por separado. El backend es un servicio HTTP autónomo,
de modo que la lógica de negocio podría reutilizarse desde otros clientes (por
ejemplo, un canal de mensajería) sin tocar la interfaz web.

Se eligió **Python con FastAPI** por ser un lenguaje idiomático y de mantenimiento
sencillo, con muy poco código para resolver cada caso, y por ser el ecosistema más
habitual para servicios de validación alrededor de modelos de lenguaje. El código
sigue el estilo de la documentación oficial de FastAPI (rutas delgadas, dependencias
e inyección de sesión) para que sea predecible y fácil de revisar.

```mermaid
flowchart LR
    U[Usuario / navegador] -->|HTTP JSON| FE[Frontend React + Vite]
    FE -->|peticiones /api| BE[Backend FastAPI]
    BE --> DB[(SQLite)]
    BE -->|HTTPS, token por sesión| RS[Servicio de reservas]
    BE -->|HTTPS, API key| AI[IA simulada]
    BE -.->|lectura local| DOCS[data/documentos.jsonl]
```

### Piezas principales

| Pieza | Papel |
| --- | --- |
| **FastAPI** | Framework HTTP y enrutado de la API. |
| **Pydantic** | Validación de tipos: cuerpos de petición, configuración y salida de la IA. |
| **SQLModel** | ORM (tablas y consultas tipadas) sobre SQLAlchemy. |
| **SQLite** | Base de datos local, elegida por simplicidad. |
| **httpx** | Cliente HTTP hacia los servicios remotos. |
| **tenacity** | Reintentos limitados ante fallos temporales. |

### Backend (`backend/`)

| Archivo | Responsabilidad |
| --- | --- |
| `app/main.py` | Aplicación FastAPI: rutas del contrato (`/api/...`) y manejadores globales de error. |
| `app/config.py` | Configuración desde `.env` (`pydantic-settings`), `User-Agent` exigido y mapa sesión → token remoto. |
| `app/database.py` | Motor SQLite, creación de tablas, dependencia de sesión y `reset_database()`. |
| `app/models.py` | Tablas y enumerados: conversaciones, mensajes, propuestas y trazas. |
| `app/sessions.py` | Sesiones de demostración, resolución del token y dependencias de rol (`GuestDep`, `ManagerDep`), más `AppError`. |
| `app/rules.py` | Corpus documental y resolución de la política vigente del hotel. |
| `app/ai_client.py` | Cliente de la IA, validación de la interpretación y reintentos limitados. |
| `app/reservations_client.py` | Cliente del servicio de reservas y excepciones tipadas. |
| `app/service.py` | Casos de uso (mensaje, listado, aprobación y rechazo) y textos al huésped. |
| `app/language.py` | Detección de idioma de respaldo, para turnos en que la IA no responde. |
| `data/documentos.jsonl` | Corpus de documentos del hotel. |
| `tests/` | Pruebas unitarias y de integración. |

El backend mantiene un **registro de seguimiento** privado por turno (identificador de
petición de la IA, propuesta asociada, documentos usados, duración y tokens
—marcados como simulados—). Nunca se muestra al huésped.

### Frontend (`frontend/`)

React 19 + Vite + TypeScript + Tailwind. **Pendiente de implementar**: por ahora es un
esqueleto que consulta `/health`. Está previsto que consuma las rutas `/api/*` del
backend y ofrezca las tres vistas del enunciado (huésped, responsable y detalle).

## Estados

### Ciclo de la propuesta

```mermaid
stateDiagram-v2
    [*] --> awaiting_approval
    awaiting_approval --> stale: la revalidación falla (reserva, reglas o disponibilidad)
    awaiting_approval --> processing: aprobada y revalidada
    awaiting_approval --> rejected: rechazada
    awaiting_approval --> awaiting_approval: simulated_rejection (503, reintentable)
    processing --> completed: recibo válido
    processing --> pending_verification: respuesta perdida o resultado incierto
    processing --> stale: conflicto al escribir
    pending_verification --> completed: reconciliación con recibo concordante
    completed --> [*]
    rejected --> [*]
    stale --> [*]
```

| Estado | Significado |
| --- | --- |
| `awaiting_approval` | Propuesta creada, pendiente de aprobación. |
| `processing` | Aprobada y revalidada; el cambio está en curso. |
| `pending_verification` | No se pudo confirmar el resultado; queda pendiente de comprobar/reconciliar. |
| `completed` | Confirmada por el servicio de reservas, con recibo. |
| `rejected` | Rechazada por el responsable; nunca se ejecuta. |
| `stale` | Los datos cambiaron (reserva, reglas o disponibilidad); exige nueva propuesta. |
| `failed` | Reservado para fallos definitivos. |

### Ciclo de un turno de mensaje

```mermaid
flowchart TD
    M[Mensaje del huésped] --> IA{La IA interpreta}
    IA -->|sin hora| NI[needs_input]
    IA -->|error o salida inválida| HO[handoff]
    IA -->|hora| ST{Reglas y disponibilidad}
    ST -->|igual o anterior| IN[information]
    ST -->|sobre el límite o sin disponibilidad| DE[declined]
    ST -->|reglas en conflicto| HO
    ST -->|válida| AP[awaiting_approval]
```

## Conexión a los servicios

Todas las claves viven **solo en el servidor** (`.env`, no versionado). La plantilla
`backend/.env.example` muestra las variables sin ningún secreto. El hotel, la reserva,
el rol y el escenario los decide siempre el backend; nunca el huésped ni la IA.

Cabeceras comunes exigidas por WorkFactory: `User-Agent: WorkFactory-Technical-Test/1.0`
y `X-Test-Scenario`, que toma el valor de la variable de entorno del escenario elegido.

### Servicio de reservas

- Base: `RESERVATIONS_BASE_URL`; escenario: `RESERVATIONS_SCENARIO`.
- Autenticación: `Authorization: Bearer <token>`, con un token **por sesión de
  demostración** resuelto en el servidor (el cliente no puede elegir token, hotel ni
  reserva).
- Rutas usadas: `GET /stays/{stay_id}`, `POST /availability/check`, `POST /changes`
  (con `expected_version` y `operation_key`) y `GET /operations/{operation_key}`.
- La ruta `POST /test/reset` se usa únicamente desde las pruebas, con
  `RESERVATIONS_TESTER_TOKEN`.

### IA simulada

- Base: `LLM_BASE_URL`; modelo: `LLM_MODEL`; escenario: `LLM_SCENARIO`.
- Autenticación: `Authorization: Bearer <LLM_API_KEY>` en `POST /chat/completions`.
- La respuesta trae, en `choices[0].message.content`, **texto que contiene otro JSON**.
  Solo se aceptan tres campos (`intent`, `requested_time`, `language`); cualquier otro
  se descarta. Un JSON roto o una hora inválida no producen cambios ni un error sin
  explicación.
- Los escenarios de fallo (`malformed-json`, `invalid-time`, `privilege-fields`,
  `transient-503`) se usan en las pruebas; el escenario `transient-503` se cubre con
  reintentos limitados (implementados con **tenacity**) que respetan `Retry-After`.

## Puesta en marcha

Las pruebas y el servidor deben ejecutarse **desde `backend/`**, porque `.env` y la base
de datos se resuelven de forma relativa a ese directorio.

### Backend

```bash
cd backend
uv sync                       # crea el entorno e instala dependencias
cp .env.example .env          # rellenar las claves descargadas de la prueba
uv run uvicorn app.main:app --reload
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

## Base de datos

SQLite, configurada con `DATABASE_URL=sqlite:///./app.db` (relativo a `backend/`). Las
tablas se crean automáticamente al arrancar la aplicación (`create_db_and_tables()`).

Se usa **SQLite por simplicidad**: no requiere servidor y basta para la prueba. Como el
acceso va siempre a través de **SQLModel** (sobre SQLAlchemy), cambiar de motor
—PostgreSQL, MySQL o una base gestionada en la nube— es sobre todo cuestión de apuntar
`DATABASE_URL` al nuevo motor e instalar su driver (`psycopg`, `pymysql`, …), además de
ajustar el `connect_args` específico de SQLite.

- **Reiniciar el entorno**: detener el servidor, borrar `backend/app.db` y volver a
  arrancar; se recrea vacío con el esquema vigente.
- **Restablecer en pruebas**: las pruebas de integración llaman a `reset_database()`
  (borra y recrea las tablas) y a `POST /test/reset` de los servicios remotos antes de
  cada caso.

## Pruebas

Dos conjuntos, separados por una marca de pytest:

- **Unitarias** (sin red): interpretación/validación de la IA, reglas, sesiones,
  permisos y detección de idioma. Se ejecutan por defecto.
- **Integración** (marca `integration`): llaman a los servicios reales, necesitan el
  `.env` con claves y reinician su estado. **No** se ejecutan por defecto.

```bash
cd backend
uv run pytest                    # solo unitarias
uv run pytest -m integration     # contra los servicios reales
```

## Resultados de los casos

Automatizados los diez grupos de `datos/casos-publicos.jsonl` (agrupando variantes) y
ejecutados contra los servicios reales.

```
uv run pytest -m integration
============ 18 passed, 1 skipped, 29 deselected ============
```

| Caso | Nombre | Resultado |
| --- | --- | --- |
| P01 | Datos incompletos y contexto | Verificado |
| P02 | Camino completo e inglés | Verificado |
| P03 | Habitación sin disponibilidad | Verificado |
| P04 | Autoridad y contradicción | Verificado (incluida la variante de dos políticas v2) |
| P05 | Inyección en mensaje y documento | Verificado |
| P06 | Aislamiento y rol | Verificado |
| P07 | Duplicados y carrera | Verificado (duplicados sí; la carrera se probó en secuencia) |
| P08 | Resultado incierto y reinicio | Pendiente: requiere `reconcile` |
| P09 | Propuesta obsoleta | Verificado (escenario `stale-availability` y variante de política) |
| P10 | Modelo inválido y rechazo | Verificado (`invalid-time`, `malformed-json`, `privilege-fields`, `transient-503`) |

### Fallos encontrados y corregidos

1. **`ReservationNotFoundError` no heredaba de `ReservationServiceError`.** Una
   reserva ajena o inexistente escapaba del mapeo de errores en lugar de traducirse al
   `403`/`404` del contrato. Se corrigió la jerarquía de excepciones.
2. **El mensaje de derivación salía siempre en español.** Con la IA caída, un huésped
   que escribía en inglés recibía la respuesta en español. Se corrigió recordando el
   idioma de la conversación y, si no lo había, estimándolo del texto.

### Pendiente

- **P08** (`response-lost` y `transient-503` con reinicio): falta la ruta
  `POST /api/proposals/{id}/reconcile`. Su prueba existe marcada como `skip`.
- **`GET /api/conversations/{conversation_id}`**: ruta del contrato aún no implementada.

## Límites y trabajo futuro

- **Idiomas.** Los idiomas (`es`, `en`) están fijados en varias capas: la validación y
  el prompt de `ai_client`, la normalización en `service` y el catálogo de textos
  `_msg_*`. Para ampliarlos sin tocar código, se extraerían a ficheros de idioma
  externos con un registro cargado al arranque, plantillas por clave y un idioma por
  defecto configurable. Además, la detección del idioma la realiza el modelo remoto,
  que hoy solo reconoce español e inglés: añadir un idioma exige también soporte en el
  proveedor (o un detector propio).
- **Frontend** sin implementar (esqueleto).
- **Reconciliación** (`reconcile`) y la ruta de conversaciones, pendientes.
- **Sin autenticación real** (sesiones de demostración) y **sin pagos**, por diseño de
  la prueba.

## Tiempo empleado

| Día | Tiempo | Trabajo |
| --- | --- | --- |
| 1 | 2 h 30 min | Estudio de requisitos y diseño de la arquitectura; esqueleto inicial con placeholders. |
| 2 | 1 h 30 min | Mayor parte del backend (clientes de servicios, modelos y reglas), sin rutas ni orquestación. |
| 3 | 1 h 30 min | Cierre del backend: rutas y capa de servicio (mensaje, propuesta, aprobación y rechazo) y pruebas. |
| 4 | 1 h 30 min (previsto) | Frontend, documentación y pruebas exhaustivas. |

Total dedicado: **5 h 30 min** en tres días; con el cuarto, **7 h**. El límite del
enunciado es de 8 h.

## Decisiones

Resumen de las tres decisiones principales; el detalle está en
[`DECISIONES.md`](DECISIONES.md).

1. **Backend desacoplado con Python y FastAPI.**
2. **Rutas delgadas y una capa de servicio aparte** (`main.py` / `service.py`).
3. **Cambios fiables**: identificador de operación idempotente y revalidación de
   reserva, reglas y disponibilidad antes de escribir.
