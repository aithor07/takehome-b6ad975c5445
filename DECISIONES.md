# Decisiones

## 1. Tres decisiones

### 1.1 Backend desacoplado con Python y FastAPI

El proyecto se divide en **frontend** y **backend** independientes, para poder
desplegar cada uno por su cuenta (por ejemplo, un contenedor propio en Docker). El
backend es un servicio HTTP autónomo, de modo que la misma lógica podría servir a otros
clientes (como un canal de mensajería) sin tocar la interfaz web.

Se eligió **Python con FastAPI** por varias razones:

- Es un lenguaje idiomático y de mantenimiento sencillo, con muy poco código para
  resolver cada caso si se compara con una alternativa como TypeScript.
- Es el ecosistema más habitual para servicios de validación alrededor de modelos de
  lenguaje, con librerías actualizadas y documentación clara.
- Seguir el estilo de la documentación oficial de FastAPI (rutas delgadas,
  dependencias, inyección de sesión) hace que el resultado sea predecible y fácil de
  revisar, también al apoyarse en herramientas de IA.

El soporte del backend se apoya en **Pydantic** (validación de tipos de las peticiones,
la configuración y la salida de la IA), **SQLModel** como ORM sobre SQLAlchemy y
**tenacity** para los reintentos ante fallos temporales. La base de datos es **SQLite
por simplicidad** (no necesita servidor); como el acceso va siempre por SQLModel, pasar
a PostgreSQL, MySQL o una base gestionada en la nube se reduce a cambiar `DATABASE_URL`
e instalar el driver correspondiente.

### 1.2 Rutas delgadas y una capa de servicio aparte

Dentro del backend, las **rutas** (`app/main.py`) se limitan al transporte: resolver la
sesión, comprobar la forma de la petición y devolver el cuerpo del contrato. La lógica
de cada caso de uso (llamar a la IA, consultar las reglas, comprobar la reserva y
decidir el siguiente estado) vive en una **capa de servicio** (`app/service.py`).

Esta separación tiene tres consecuencias:

- Los casos de uso se pueden **probar sin HTTP**, porque no dependen del transporte.
- La ruta queda corta y legible, y hay un único sitio donde vive cada caso de uso.
- Cambiar o añadir una interfaz (web, mensajería) no obliga a duplicar la lógica.

### 1.3 Cambios fiables: idempotencia y revalidación

Modificar la reserva es la operación de mayor riesgo, así que se protege en varios
puntos:

- Cada propuesta conserva un **identificador de operación** estable, de forma que
  reintentar o reconciliar nunca duplica un cambio.
- Una aprobación cubre reserva, hora, importe y versión de las reglas. Antes de
  escribir, el servidor **revalida**: si cambió la reserva, las reglas o la
  disponibilidad, la propuesta pasa a `stale` y exige una nueva aprobación.
- Una propuesta rechazada nunca se ejecuta.
- Un resultado incierto (respuesta perdida) deja la propuesta en
  `pending_verification`, sin afirmar éxito ni fallo.

## 2. Ayuda de IA utilizada

- **Herramienta**: OpenCode como *harness* de agente, con un modelo **Qwen 3.8 27B**
  ejecutado en local. Todo el trabajo es local y privado; ninguna clave del proyecto se
  comparte con la IA.
- **Para qué se usó**:
  - Guiarme para mantener el código dentro de los límites y restricciones de la prueba
    (contratos, cabeceras, escenarios y estados exigidos).
  - Automatización de las pruebas.
  - Sustituir la lectura manual de documentación (FastAPI, Pydantic, SQLModel) cuando
    hacía falta un detalle concreto.
  - Acelerar la escritura de código repetitivo a partir de un ejemplo.
  - Redactar el README.md y DECISIONES.md bien formateados a partir de una plantilla en sucio.
- **Frontend** (pendiente): está previsto usar la IA con *skills* para un diseño
  acorde a los requisitos y al consumo del backend.
- Todo resultado generado con IA se **revisa y se justifica**: el enunciado permite
  usar IA, pero exige comprobar el resultado y explicar el código entregado.

## 3. Dos fallos reproducidos y corregidos

### 3.1 `ReservationNotFoundError` no heredaba de `ReservationServiceError`

- **Síntoma**: una reserva ajena o inexistente no producía el `403`/`404` del contrato,
  sino un error no controlado.
- **Reproducción**: petición sobre una reserva que no pertenece a la sesión; la
  respuesta no era la esperada del contrato.
- **Causa**: `ReservationNotFoundError` no heredaba de `ReservationServiceError`, así
  que el `except` de la capa de servicio no lo capturaba y escapaba de nuestro
  manejador de errores.
- **Corrección**: hacer que herede de `ReservationServiceError`.
- **Por qué**: centraliza el mapeo de errores y garantiza que una reserva ajena se
  traduzca siempre al código del contrato, sin filtrar información.

### 3.2 El mensaje de derivación salía siempre en español

- **Síntoma**: cuando la IA no respondía o devolvía una salida inválida, un huésped que
  escribía en inglés recibía el mensaje al huésped en español.
- **Reproducción**: forzar un escenario de fallo de la IA (`invalid-time`,
  `malformed-json` o `transient-503`) con un mensaje en inglés.
- **Causa**: en el camino de fallo, el idioma estaba fijo a `"es"`
  (`_msg_revision("es")`), porque el idioma se obtenía de la IA y en esa rama no hay
  resultado.
- **Corrección**: recordar el último idioma conocido de la conversación (se guarda al
  interpretar correctamente un turno) y, si no lo hay, estimarlo del texto del huésped
  con un detector ligero (`app/language.py`), con español por defecto.
- **Por qué**: el idioma del mensaje forma parte de la corrección de la respuesta;
  contestar en el idioma del huésped es parte del contrato del caso de ejemplo.
