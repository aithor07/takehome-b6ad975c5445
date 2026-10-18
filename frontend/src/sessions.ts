// Sesiones de demostracion del kit (datos/identidades.json).
//
// No son un inicio de sesion ni tokens reales: el backend resuelve rol, hotel y
// reserva a partir del codigo. La web solo elige cual presenta, y nunca manda
// rol, hotel ni reserva en el cuerpo de una peticion: eso lo decide el servidor.

export type Role = "guest" | "manager";

export type DemoSession = {
  token: string;
  role: Role;
  // Nombre corto para el selector.
  name: string;
  hotelId: string;
  // Null en las sesiones de responsable: no tienen reserva propia.
  stayId: string | null;
};

export const SESSIONS: DemoSession[] = [
  {
    token: "guest-a1",
    role: "guest",
    name: "Huésped A1",
    hotelId: "hotel-alba",
    stayId: "STAY-A1",
  },
  {
    token: "guest-a2",
    role: "guest",
    name: "Huésped A2",
    hotelId: "hotel-alba",
    stayId: "STAY-A2",
  },
  {
    token: "guest-b1",
    role: "guest",
    name: "Huésped B1",
    hotelId: "hotel-alba-b",
    stayId: "STAY-B1",
  },
  {
    token: "manager-a",
    role: "manager",
    name: "Recepción Alba",
    hotelId: "hotel-alba",
    stayId: null,
  },
  {
    token: "manager-b",
    role: "manager",
    name: "Recepción Brisa",
    hotelId: "hotel-alba-b",
    stayId: null,
  },
];

export function sessionsOf(role: Role): DemoSession[] {
  return SESSIONS.filter((session) => session.role === role);
}

export function findSession(token: string): DemoSession | null {
  return SESSIONS.find((session) => session.token === token) ?? null;
}

export function defaultToken(role: Role): string {
  return sessionsOf(role)[0]?.token ?? "";
}

// La sesion pedida, o la primera de su rol: la interfaz nunca queda sin sesion
// aunque el almacenamiento traiga un codigo de un kit anterior.
export function sessionFor(role: Role, token: string): DemoSession {
  const found = findSession(token);
  if (found !== null && found.role === role) return found;
  return sessionsOf(role)[0];
}

// --- Persistencia de la sesion elegida --------------------------------------
// Recargar la pagina no debe devolver al evaluador a la primera sesion.

const STORAGE_PREFIX = "salida-mas-tarde.";

export function loadToken(role: Role): string | null {
  try {
    return window.localStorage.getItem(`${STORAGE_PREFIX}${role}`);
  } catch {
    return null;
  }
}

export function saveToken(role: Role, token: string): void {
  try {
    window.localStorage.setItem(`${STORAGE_PREFIX}${role}`, token);
  } catch {
    // Sin almacenamiento disponible (modo privado): la sesion vive en memoria.
  }
}

// --- Conversacion -----------------------------------------------------------
// El huésped no elige conversacion: se deriva de su reserva, de forma estable.
// Asi la misma reserva siempre vuelve al mismo hilo y el historial persiste
// entre recargas, que es justo lo que pide el encargo ("reiniciar la aplicacion
// debe conservar el trabajo"). STAY-A1 -> conv-a1, el ejemplo del contrato.

export function conversationFor(stayId: string): string {
  return `conv-${stayId.replace(/^STAY-/i, "").toLowerCase()}`;
}
