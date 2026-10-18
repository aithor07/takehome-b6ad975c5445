// Vocabulario de presentacion: el unico sitio donde el contrato se traduce a
// texto, forma y color. Los componentes no repiten literales de estado.

import type { MessageStatus, ProposalStatus } from "./api";

export type Badge = {
  label: string;
  className: string;
};

// El sello es el unico elemento con caracter de la interfaz: reproduce el
// artefacto real del mostrador, una propuesta a la que se le estampa su estado.
// Tres formas, y siempre ademas la palabra escrita, para que el estado no
// dependa solo del color:
//
//   relleno y girado .... espera que alguien actue
//   contorno recto ...... cerrado, decision tomada
//   contorno discontinuo  hay que mirarlo a mano
const SELLO =
  "inline-flex items-center rounded-sello border-2 px-2 py-0.5 text-xs font-semibold";

const ABIERTO = `${SELLO} -rotate-1 border-coral bg-coral text-white`;
const DUDA = `${SELLO} -rotate-1 border-violeta bg-violeta text-white`;
const HECHO = `${SELLO} border-sal text-sal`;
const CERRADO = `${SELLO} border-tinta-suave text-tinta-suave`;
const REVISAR = `${SELLO} border-dashed border-coral text-coral`;

// --- Propuestas -------------------------------------------------------------
// Los cinco estados que el enunciado pide distinguir tienen etiqueta propia:
// pendiente de aprobacion, cambio sin comprobar, completado, rechazado y
// requiere revision.

const PROPOSAL_BADGE: Record<ProposalStatus, Badge> = {
  awaiting_approval: { label: "Pendiente de aprobación", className: ABIERTO },
  processing: { label: "Ejecutando", className: DUDA },
  pending_verification: { label: "Cambio sin comprobar", className: DUDA },
  completed: { label: "Completado", className: HECHO },
  rejected: { label: "Rechazado", className: CERRADO },
  stale: { label: "Requiere revisión", className: REVISAR },
  failed: { label: "Falló", className: REVISAR },
};

export function proposalBadge(status: ProposalStatus): Badge {
  return PROPOSAL_BADGE[status] ?? { label: status, className: CERRADO };
}

// --- Mensajes del huesped ---------------------------------------------------

const MESSAGE_BADGE: Record<MessageStatus, Badge> = {
  needs_input: { label: "Falta la hora", className: CERRADO },
  information: { label: "Información", className: CERRADO },
  awaiting_approval: { label: "Pendiente de aprobación", className: ABIERTO },
  declined: { label: "No disponible", className: CERRADO },
  handoff: { label: "Revisión humana", className: REVISAR },
};

export function messageBadge(status: MessageStatus): Badge {
  return MESSAGE_BADGE[status] ?? { label: status, className: CERRADO };
}

// --- Que se puede hacer con una propuesta -----------------------------------

// El responsable puede aprobarla o rechazarla.
export function canDecide(status: ProposalStatus): boolean {
  return status === "awaiting_approval";
}

// El resultado aun no se conoce: se puede comprobar contra el servicio.
export function canReconcile(status: ProposalStatus): boolean {
  return status === "processing" || status === "pending_verification";
}

// Decision ya tomada: no se ejecuta nada mas ni se vuelve a decidir.
export function isSettled(status: ProposalStatus): boolean {
  return (
    status === "completed" ||
    status === "rejected" ||
    status === "stale" ||
    status === "failed"
  );
}

// Requiere que lo mire una persona del hotel.
export function needsReview(status: ProposalStatus): boolean {
  return status === "stale" || status === "failed";
}

// --- Formateo ---------------------------------------------------------------

export const NO_DATA = "—";

// La hora se recorta del ISO en UTC a proposito: con new Date() el navegador la
// desplazaria a su zona y el kit trabaja en UTC. En Madrid, las 11:00 del
// enunciado se verian como 13:00 y la pantalla contradiria al encargo.
export function hour(iso: string | null): string {
  if (!iso || iso.length < 16) return NO_DATA;
  return iso.slice(11, 16);
}

export function shortDate(iso: string | null): string {
  if (!iso || iso.length < 10) return NO_DATA;
  const [year, month, day] = iso.slice(0, 10).split("-");
  return `${day}/${month}/${year}`;
}

export function dateTime(iso: string | null): string {
  if (!iso || iso.length < 16) return NO_DATA;
  return `${shortDate(iso)} ${hour(iso)}`;
}

export function euros(amount: number): string {
  return `${amount} EUR`;
}

export function millis(value: number | null): string {
  return value === null ? NO_DATA : `${value} ms`;
}

export function tokens(value: number | null): string {
  return value === null ? NO_DATA : String(value);
}

// Primeros caracteres de un identificador, para tablas estrechas.
export function shortId(id: string): string {
  return id.slice(0, 8);
}

// "HH:MM" a minutos desde medianoche. Null si no es una hora valida.
export function minutesOf(hhmm: string): number | null {
  const parts = hhmm.split(":");
  if (parts.length !== 2) return null;
  const h = Number(parts[0]);
  const m = Number(parts[1]);
  if (Number.isNaN(h) || Number.isNaN(m)) return null;
  return h * 60 + m;
}

// Separacion entre dos instantes, en formato corto: "+3 h", "+1 h 30 min".
export function hourShift(fromIso: string | null, toIso: string | null): string {
  const from = minutesOf(hour(fromIso));
  const to = minutesOf(hour(toIso));
  if (from === null || to === null) return NO_DATA;

  const total = to - from;
  if (total === 0) return "sin cambio";

  const sign = total > 0 ? "+" : "-";
  const abs = Math.abs(total);
  const h = Math.floor(abs / 60);
  const m = abs % 60;
  if (h === 0) return `${sign}${m} min`;
  if (m === 0) return `${sign}${h} h`;
  return `${sign}${h} h ${m} min`;
}

// --- Decisiones y botones ---------------------------------------------------
// El contrato responde 200, 202 o 409, y los tres son respuestas, no fallos: el
// color solo matiza si el cambio quedo hecho, sin confirmar o no se pudo hacer.

export function decisionTone(httpStatus: number): string {
  if (httpStatus === 200) return "text-sal";
  if (httpStatus === 202) return "text-violeta";
  return "text-coral";
}

const BUTTON_BASE =
  "rounded-sello px-3 py-1 text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-40";

export const BUTTON_PRIMARY = `${BUTTON_BASE} bg-tinta text-white`;
export const BUTTON_QUIET = `${BUTTON_BASE} border border-tinta-suave/40 hover:border-tinta`;
export const BUTTON_DANGER = `${BUTTON_BASE} border border-coral/40 text-coral hover:border-coral`;

// --- Banda horaria ----------------------------------------------------------
// Franja del dia que muestra el mostrador. Solo se marca la salida actual y la
// pedida; el limite del hotel no se deduce, se cita con su documento al lado.

export const BAND_FROM = "10:00";
export const BAND_TO = "18:00";

// Posicion 0-100 dentro de la banda, recortada a los extremos.
export function bandPosition(hhmm: string): number | null {
  const at = minutesOf(hhmm);
  const from = minutesOf(BAND_FROM);
  const to = minutesOf(BAND_TO);
  if (at === null || from === null || to === null || to === from) return null;

  const percent = ((at - from) / (to - from)) * 100;
  return Math.min(100, Math.max(0, percent));
}
