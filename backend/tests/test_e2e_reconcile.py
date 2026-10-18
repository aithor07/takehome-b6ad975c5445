"""Flujo de conciliacion (P08) contra los servicios reales.

Pendiente: necesita `POST /api/proposals/{id}/reconcile`, aun no implementado.
Cuando exista, quitar el `skip` y completar el flujo:
  - escenario("response-lost"): `approve` deja la propuesta en
    `pending_verification` (202) sin exito ni fallo definitivo;
  - `reconcile` con la misma `operation_key` y un recibo concordante -> 200 completed.

Ejecutar con:  pytest -m integration
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.skip(reason="reconcile aun no implementado (P08)")
def test_p08_resultado_incierto_y_reconciliacion(client, estado_limpio, escenario):
    escenario(reservations="response-lost")
    # TODO: crear propuesta, aprobar y comprobar pending_verification + reconcile.
