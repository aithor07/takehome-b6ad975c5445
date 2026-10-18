import { useCallback, useEffect, useState } from "react";
import {
  describeError,
  getConversation,
  isApiError,
  sendMessage,
  type Conversation,
  type Proposal,
} from "./api";
import {
  dateTime,
  euros,
  hour,
  hourShift,
  messageBadge,
  proposalBadge,
  shortId,
} from "./presentation";
import { conversationFor, type DemoSession } from "./sessions";
import TimeBand from "./TimeBand";

type GuestViewProps = {
  session: DemoSession;
};

// Frases de arranque para la demo: la primera pide la hora directamente, la
// segunda obliga a la IA a preguntarla y la tercera es la respuesta a esa
// pregunta conservando el hilo.
const EXAMPLES = ["Quiero salir a las 14:00", "¿Puedo salir más tarde?", "A las 15:00"];

export default function GuestView({ session }: GuestViewProps) {
  const stayId = session.stayId;
  const conversationId = stayId === null ? "" : conversationFor(stayId);

  const [conversation, setConversation] = useState<Conversation | null>(null);
  // La primera carga ya esta en marcha al montar, asi que empieza encendido.
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [text, setText] = useState("");

  // Encadenado, y no async/await, para que la carga inicial no dispare renders en
  // cascada: los cambios de estado van dentro de las callbacks de la promesa.
  const load = useCallback(() => {
    if (stayId === null) return Promise.resolve();
    return getConversation(session.token, conversationId)
      .then((data) => {
        setConversation(data);
        setError(null);
        setLoading(false);
      })
      .catch((caught: unknown) => {
        // Un 404 es el estado normal mientras el huesped no ha escrito nada.
        if (isApiError(caught) && caught.status === 404) {
          setConversation(null);
          setError(null);
        } else {
          setError(describeError(caught));
        }
        setLoading(false);
      });
  }, [conversationId, session.token, stayId]);

  // Al cambiar de sesion App vuelve a montar esta vista (key), asi que no hace
  // falta limpiar el estado anterior: nace vacio.
  useEffect(() => {
    void load();
  }, [load]);

  async function send() {
    const value = text.trim();
    if (value === "" || stayId === null || sending) return;

    setSending(true);
    try {
      await sendMessage(session.token, {
        event_id: crypto.randomUUID(),
        conversation_id: conversationId,
        stay_id: stayId,
        text: value,
      });
      setText("");
      // Encenderlo desde un manejador (no desde un efecto) es lo que evita el
      // setState sincrono en el arranque.
      setLoading(true);
      await load();
    } catch (caught) {
      setError(describeError(caught));
    } finally {
      setSending(false);
    }
  }

  if (stayId === null) {
    return (
      <p className="rounded-sello border border-tinta-suave/25 bg-white px-4 py-3 text-sm">
        Esta sesión no tiene reserva asociada. Elige una sesión de huésped en la cabecera.
      </p>
    );
  }

  const messages = conversation?.messages ?? [];
  const proposals = conversation?.proposals ?? [];
  const latest = proposals.length > 0 ? proposals[proposals.length - 1] : null;

  return (
    <div className="grid gap-6 lg:grid-cols-12">
      <section className="flex flex-col rounded-sello border border-tinta-suave/25 bg-white lg:col-span-7">
        <header className="flex items-baseline justify-between gap-3 border-b border-tinta-suave/20 px-4 py-3">
          <h2 className="text-sm font-semibold">Conversación</h2>
          <span className="text-xs tabular-nums text-tinta-suave">
            {loading ? "Actualizando" : `Reserva ${stayId}`}
          </span>
        </header>

        <div className="flex-1 space-y-5 px-4 py-4">
          {messages.length === 0 && (
            <p className="text-sm text-tinta-suave">
              Todavía no hay mensajes. Escribe la hora a la que necesitas salir y el hotel
              contestará con los datos de la reserva.
            </p>
          )}

          {messages.map((item) => {
            const badge = messageBadge(item.status);
            return (
              <div key={item.event_id} className="space-y-2">
                {item.text !== "" && (
                  <div className="flex justify-end">
                    <p className="max-w-[85%] rounded-sello bg-tinta px-3 py-2 text-sm text-white">
                      {item.text}
                    </p>
                  </div>
                )}

                {item.message !== null && (
                  <div className="space-y-1.5">
                    <p
                      lang={conversation?.language ?? undefined}
                      className="max-w-[85%] rounded-sello border border-tinta-suave/25 bg-cal px-3 py-2 text-sm"
                    >
                      {item.message}
                    </p>
                    <div className="flex items-center gap-2">
                      <span className={badge.className}>{badge.label}</span>
                      <time className="text-[11px] tabular-nums text-tinta-suave">
                        {dateTime(item.created_at)}
                      </time>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>

        {error !== null && (
          <p className="border-t border-coral/40 bg-coral/5 px-4 py-2 text-sm text-coral">
            {error}
          </p>
        )}

        <form
          className="border-t border-tinta-suave/20 px-4 py-3"
          onSubmit={(event) => {
            event.preventDefault();
            void send();
          }}
        >
          <div className="flex flex-wrap gap-2 pb-2">
            {EXAMPLES.map((example) => (
              <button
                key={example}
                type="button"
                onClick={() => setText(example)}
                className="rounded-sello border border-tinta-suave/30 px-2 py-1 text-xs text-tinta-suave hover:border-tinta hover:text-tinta"
              >
                {example}
              </button>
            ))}
          </div>

          <div className="flex items-end gap-2">
            <label className="flex-1">
              <span className="sr-only">Mensaje para el hotel</span>
              <textarea
                value={text}
                onChange={(event) => setText(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault();
                    void send();
                  }
                }}
                rows={2}
                placeholder="A las 14:00"
                className="w-full resize-none rounded-sello border border-tinta-suave/30 bg-white px-3 py-2 text-sm placeholder:text-tinta-suave/70"
              />
            </label>
            <button
              type="submit"
              disabled={sending || text.trim() === ""}
              className="rounded-sello bg-tinta px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-40"
            >
              Enviar
            </button>
          </div>

          {conversation?.language === "en" && (
            <p className="pt-2 text-xs text-tinta-suave">
              El huésped está escribiendo en inglés y el hotel responde en inglés.
            </p>
          )}
        </form>
      </section>

      <section className="lg:col-span-5">
        {latest === null ? (
          <div className="rounded-sello border border-dashed border-tinta-suave/40 px-4 py-5">
            <h2 className="text-sm font-semibold">Solicitud de salida tardía</h2>
            <p className="mt-1 text-sm text-tinta-suave">
              Cuando pidas una hora, aquí verás la salida actual, la nueva, el importe y el
              documento del hotel que lo respalda.
            </p>
          </div>
        ) : (
          <ProposalCard proposal={latest} />
        )}
      </section>
    </div>
  );
}

function ProposalCard({ proposal }: { proposal: Proposal }) {
  const badge = proposalBadge(proposal.status);

  return (
    <article className="rounded-sello border border-tinta-suave/25 bg-white">
      <header className="flex items-start justify-between gap-3 border-b border-tinta-suave/20 px-4 py-3">
        <div>
          <h2 className="text-sm font-semibold">Solicitud de salida tardía</h2>
          <p className="text-xs tabular-nums text-tinta-suave">Reserva {proposal.stay_id}</p>
        </div>
        <span className={badge.className}>{badge.label}</span>
      </header>

      <div className="px-4 py-3">
        <TimeBand
          currentIso={proposal.current_checkout_at}
          requestedIso={proposal.requested_checkout_at}
        />

        <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
          <Field label="Salida actual" value={hour(proposal.current_checkout_at)} />
          <Field label="Salida pedida" value={hour(proposal.requested_checkout_at)} />
          <Field
            label="Cambio"
            value={hourShift(proposal.current_checkout_at, proposal.requested_checkout_at)}
          />
          <Field label="Importe" value={euros(proposal.fee_eur)} />
        </dl>

        <div className="mt-4 border-t border-tinta-suave/20 pt-3">
          <p className="text-xs text-tinta-suave">Documento del hotel que lo respalda</p>
          <p className="mt-1 text-sm font-semibold">
            {proposal.policy_document_id} (versión {proposal.policy_version})
          </p>
          <blockquote className="mt-2 border-l-2 border-sal pl-3 text-sm">
            {proposal.evidence.quote}
          </blockquote>
        </div>

        <p className="mt-4 border-t border-tinta-suave/20 pt-3 text-sm">
          {guestStatusText(proposal)}
        </p>

        {proposal.receipt !== null && (
          <dl className="mt-2 space-y-1 text-xs text-tinta-suave">
            <div className="flex gap-2">
              <dt>Confirmación</dt>
              <dd className="tabular-nums">{shortId(proposal.receipt.change_id)}</dd>
            </div>
            <div className="flex gap-2">
              <dt>Salida confirmada</dt>
              <dd className="tabular-nums">{hour(proposal.receipt.checkout_at)}</dd>
            </div>
          </dl>
        )}
      </div>
    </article>
  );
}

// El huesped no ve registros internos: solo el estado y lo que ya consta. Por
// eso aqui nunca se afirma exito ni fallo mientras el cambio no este comprobado.
function guestStatusText(proposal: Proposal): string {
  switch (proposal.status) {
    case "awaiting_approval":
      return "Esperando que el hotel apruebe. Todavía no se ha cambiado la reserva.";
    case "processing":
      return "El cambio está en marcha. El hotel comprobará si se ha aplicado.";
    case "pending_verification":
      return "El hotel está comprobando si el cambio se aplicó. Todavía no hay confirmación.";
    case "completed":
      return "Cambio confirmado por el servicio de reservas.";
    case "rejected":
      return "El hotel ha rechazado la solicitud. La reserva no ha cambiado.";
    case "stale":
      return "Esta solicitud quedó obsoleta: los datos de la reserva cambiaron. Pide la hora de nuevo.";
    case "failed":
      return "El cambio no se pudo aplicar. La reserva sigue como estaba.";
    default:
      return "";
  }
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs text-tinta-suave">{label}</dt>
      <dd className="font-semibold tabular-nums">{value}</dd>
    </div>
  );
}
