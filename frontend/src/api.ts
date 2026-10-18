export const API_BASE_URL: string = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

//Estados de una propuesta
export type ProposalStatus =
  | "awaiting_approval"
  | "processing"
  | "pending_verification"
  | "completed"
  | "rejected"
  | "stale"
  | "failed";



//Estados de la respuesta a un mensaje de huesped
export type MessageStatus =
  | "needs_input"
  | "information"
  | "awaiting_approval"
  | "declined"
  | "handoff";


//Horario, limite e importe de la propuesta
export type Evidence = {
  document_id: string;
  version: number;
  quote: string;
};

//Confirmacion del servicio de reservas cuando el cambio ocurre
export type Receipt = {
  stay_id: string;
  checkout_at: string;
  version: number;
  operation_key: string;
  change_id: string;
};


//Formato de una propuesta
export type Proposal = {
  id: string;
  // Null solo si la conversacion no se pudiera resolver; el detalle lo tolera.
  conversation_id: string | null;
  stay_id: string;
  status: ProposalStatus;
  current_checkout_at: string;
  requested_checkout_at: string;
  fee_eur: number;
  policy_document_id: string;
  policy_version: number;
  evidence: Evidence;
  operation_key: string;
  receipt: Receipt | null;
};


//Cuerpo comun de las tres decisiones aprobar, rechazar y reconciliar
export type Decision = {
  proposal_id: string;
  status: ProposalStatus;
  message: string;
  receipt: Receipt | null;
};

//Decision acompañada de codigo http
export type DecisionResult = {
  httpStatus: number;
  decision: Decision;
};


export type MessageRequest = {
  event_id: string;
  conversation_id: string;
  stay_id: string;
  text: string;
};


export type MessageReply = {
  event_id: string;
  conversation_id: string;
  status: MessageStatus;
  message: string;
  proposal_id: string | null;
  trace_id: string;
  //true cuando el event_id ya existia con el mismo contenido. 
  replayed: boolean;
};


export type ConversationMessage = {
  event_id: string;
  //Lo que escribio el huesped: sin esto el historial solo tendria las respuestas
  text: string;
  status: MessageStatus;
  message: string | null;
  proposal_id: string | null;
  created_at: string;
};

//Registro de seguimiento interno, solo de backend a manager
export type Trace = {
  http_request_id: string | null;
  duration_ms: number | null;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  tokens_simulated: number | null;
  detail: Record<string, unknown> | null;
  created_at: string;
};

export type Conversation = {
  conversation_id: string;
  stay_id: string;
  hotel_id: string;
  language: string | null;
  messages: ConversationMessage[];
  proposals: Proposal[];
  // Presente solo cuando la peticion la hace un responsable.
  traces?: Trace[];
};


export type ApiError = {
  status: number;
  code: string;
  message: string;
};

export function isApiError(value: unknown): value is ApiError {
  if (typeof value !== "object" || value === null) return false;
  const posible = value as Partial<ApiError>;
  return (
    typeof posible.status === "number" &&
    typeof posible.code === "string" &&
    typeof posible.message === "string"
  );
}

// Texto listo para pantalla a partir de cualquier fallo capturado.
export function describeError(value: unknown): string {
  if (isApiError(value)) return `${value.message} (${value.status} · ${value.code})`;
  if (value instanceof Error) return value.message;
  return "Error inesperado";
}

function errorDeRed(): ApiError {
  return {
    status: 0,
    code: "network_error",
    message: "No se pudo contactar con el servidor",
  };
}

function errorDeContrato(status: number, body: unknown): ApiError {
  const envelope = body as { error?: { code?: unknown; message?: unknown } } | null;
  const code =
    typeof envelope?.error?.code === "string" ? envelope.error.code : "http_error";
  const message =
    typeof envelope?.error?.message === "string"
      ? envelope.error.message
      : `Error HTTP ${status}`;
  return { status, code, message };
}

async function leerCuerpo(response: Response): Promise<unknown> {
  const texto = await response.text();
  if (!texto) return null;
  try {
    return JSON.parse(texto);
  } catch {
    return null;
  }
}

type Metodo = "GET" | "POST";

async function peticion<T>(
  ruta: string,
  token: string | null,
  opciones: { method?: Metodo; body?: unknown } = {},
): Promise<T> {
  const headers: Record<string, string> = {};
  if (token !== null) headers["Authorization"] = `Bearer ${token}`;
  if (opciones.body !== undefined) headers["Content-Type"] = "application/json";

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${ruta}`, {
      method: opciones.method ?? "GET",
      headers,
      body: opciones.body === undefined ? undefined : JSON.stringify(opciones.body),
    });
  } catch {
    throw errorDeRed();
  }

  const cuerpo = await leerCuerpo(response);
  if (!response.ok) throw errorDeContrato(response.status, cuerpo);
  return cuerpo as T;
}

async function decision(ruta: string, token: string): Promise<DecisionResult> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${ruta}`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
    });
  } catch {
    throw errorDeRed();
  }

  const cuerpo = await leerCuerpo(response);
  // 200 completado, 202 aun sin comprobar, 409 no ejecutable: los tres son respuesta.
  if (response.status === 200 || response.status === 202 || response.status === 409) {
    return { httpStatus: response.status, decision: cuerpo as Decision };
  }
  throw errorDeContrato(response.status, cuerpo);
}

export function checkHealth(): Promise<{ status: string }> {
  return peticion<{ status: string }>("/health", null);
}

export function sendMessage(token: string, body: MessageRequest): Promise<MessageReply> {
  return peticion<MessageReply>("/api/messages", token, { method: "POST", body });
}

export function listProposals(token: string): Promise<{ proposals: Proposal[] }> {
  return peticion<{ proposals: Proposal[] }>("/api/proposals", token);
}

export function getConversation(token: string, conversationId: string): Promise<Conversation> {
  return peticion<Conversation>(
    `/api/conversations/${encodeURIComponent(conversationId)}`,
    token,
  );
}

export function approveProposal(token: string, id: string): Promise<DecisionResult> {
  return decision(`/api/proposals/${encodeURIComponent(id)}/approve`, token);
}

export function rejectProposal(token: string, id: string): Promise<DecisionResult> {
  return decision(`/api/proposals/${encodeURIComponent(id)}/reject`, token);
}

export function reconcileProposal(token: string, id: string): Promise<DecisionResult> {
  return decision(`/api/proposals/${encodeURIComponent(id)}/reconcile`, token);
}