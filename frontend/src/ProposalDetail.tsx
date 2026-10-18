import { useCallback, useEffect, useRef, useState } from "react";
import {
  approveProposal,
  describeError,
  getConversation,
  reconcileProposal,
  rejectProposal,
  type Conversation,
  type DecisionResult,
  type Proposal,
} from "./api";
import {
  BUTTON_DANGER,
  BUTTON_PRIMARY,
  BUTTON_QUIET,
  canDecide,
  canReconcile,
  dateTime,
  decisionTone,
  euros,
  hour,
  hourShift,
  millis,
  needsReview,
  proposalBadge,
  tokens,
} from "./presentation";
import type { DemoSession } from "./sessions";
import TimeBand from "./TimeBand";

type ProposalDetailProps = {
  session: DemoSession;
  proposal: Proposal;
  onClose: () => void;
};

// Pantalla de detalle, solo para el responsable: el documento que respalda la
// propuesta y el registro de la operacion. Aqui si aparecen las trazas internas,
// porque el backend solo las devuelve con token de responsable.
export default function ProposalDetail({ session, proposal, onClose }: ProposalDetailProps) {
  const conversationId = proposal.conversation_id;

  const [conversation, setConversation] = useState<Conversation | null>(null);
  // Sin conversacion no hay registro que cargar, asi que el aviso no se enciende.
  const [loading, setLoading] = useState(conversationId !== null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<DecisionResult | null>(null);
  const panel = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    panel.current?.focus();
  }, []);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  // Cadena de promesas: los cambios de estado quedan dentro de las callbacks, asi
  // la carga no provoca renders en cascada desde el efecto de arranque.
  const load = useCallback(() => {
    if (conversationId === null) return Promise.resolve();
    return getConversation(session.token, conversationId)
      .then((data) => {
        setConversation(data);
        setError(null);
        setLoading(false);
      })
      .catch((caught: unknown) => {
        setError(describeError(caught));
        setLoading(false);
      });
  }, [conversationId, session.token]);

  useEffect(() => {
    void load();
  }, [load]);

  // Tras decidir, el estado bueno es el que devuelve el servidor, no el que
  // tuvieramos en memoria.
  const shown = conversation?.proposals.find((item) => item.id === proposal.id) ?? proposal;
  const badge = proposalBadge(shown.status);
  const traces = conversation?.traces ?? [];

  async function decide(call: (token: string, proposalId: string) => Promise<DecisionResult>) {
    setBusy(true);
    try {
      const outcome = await call(session.token, proposal.id);
      setResult(outcome);
      setError(null);
      await load();
    } catch (caught) {
      setError(describeError(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto bg-tinta/40 p-3 sm:p-6">
      <div
        ref={panel}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-label="Detalle de la propuesta"
        className="mx-auto w-full max-w-5xl rounded-sello bg-white outline-none"
      >
        <header className="flex flex-wrap items-start justify-between gap-3 border-b border-tinta-suave/20 px-5 py-4">
          <div>
            <h2 className="text-base font-semibold">Detalle de la propuesta</h2>
            <p className="text-xs tabular-nums text-tinta-suave">Reserva {shown.stay_id}</p>
          </div>
          <div className="flex items-center gap-3">
            <span className={badge.className}>{badge.label}</span>
            <button type="button" onClick={onClose} className={BUTTON_QUIET}>
              Cerrar
            </button>
          </div>
        </header>

        {error !== null && (
          <p className="border-b border-coral/40 bg-coral/5 px-5 py-2 text-sm text-coral">
            {error}
          </p>
        )}

        <div className="grid gap-6 px-5 py-4 lg:grid-cols-12">
          <section className="lg:col-span-7">
            <h3 className="text-sm font-semibold">Documento que respalda la propuesta</h3>
            <p className="mt-1 text-sm font-semibold">
              {shown.policy_document_id} (versión {shown.policy_version})
            </p>
            <blockquote className="mt-2 border-l-2 border-sal pl-3 text-sm">
              {shown.evidence.quote}
            </blockquote>

            <TimeBand
              currentIso={shown.current_checkout_at}
              requestedIso={shown.requested_checkout_at}
            />

            <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
              <Field label="Salida actual" value={hour(shown.current_checkout_at)} />
              <Field label="Salida pedida" value={hour(shown.requested_checkout_at)} />
              <Field
                label="Cambio"
                value={hourShift(shown.current_checkout_at, shown.requested_checkout_at)}
              />
              <Field label="Importe" value={euros(shown.fee_eur)} />
            </dl>

            {canDecide(shown.status) || canReconcile(shown.status) ? (
              <div className="mt-4 flex flex-wrap gap-2 border-t border-tinta-suave/20 pt-3">
                {canDecide(shown.status) && (
                  <>
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => void decide(approveProposal)}
                      className={BUTTON_PRIMARY}
                    >
                      Aprobar
                    </button>
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => void decide(rejectProposal)}
                      className={BUTTON_DANGER}
                    >
                      Rechazar
                    </button>
                  </>
                )}
                {canReconcile(shown.status) && (
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => void decide(reconcileProposal)}
                    className={BUTTON_QUIET}
                  >
                    Comprobar
                  </button>
                )}
              </div>
            ) : (
              <p className="mt-4 border-t border-tinta-suave/20 pt-3 text-sm text-tinta-suave">
                {needsReview(shown.status)
                  ? "Los datos de la reserva o de las reglas cambiaron: hay que rehacer la solicitud. Este cambio no se puede ejecutar."
                  : "Propuesta cerrada: no se ejecuta nada más."}
              </p>
            )}

            {result !== null && (
              <p className={`mt-3 text-sm ${decisionTone(result.httpStatus)}`}>
                {result.decision.message}
                <span className="ml-2 text-[11px]">HTTP {result.httpStatus}</span>
              </p>
            )}
          </section>

          <section className="lg:col-span-5">
            <h3 className="text-sm font-semibold">Registro de la operación</h3>
            <p className="mt-1 text-xs text-tinta-suave">
              Solo lo recibe el responsable. La pantalla del huésped no muestra este registro.
            </p>

            <dl className="mt-3 space-y-2 text-xs">
              <div>
                <dt className="text-tinta-suave">Identificador de operación</dt>
                <dd className="break-all tabular-nums">{shown.operation_key}</dd>
              </div>
              <div>
                <dt className="text-tinta-suave">Estado en el servidor</dt>
                <dd className="tabular-nums">{shown.status}</dd>
              </div>
            </dl>

            {shown.receipt !== null && (
              <div className="mt-3 border-t border-tinta-suave/20 pt-3">
                <h4 className="text-sm font-semibold">Confirmación del servicio</h4>
                <dl className="mt-1 space-y-1 text-xs">
                  <div className="flex gap-2">
                    <dt className="text-tinta-suave">Identificador del cambio</dt>
                    <dd className="break-all tabular-nums">{shown.receipt.change_id}</dd>
                  </div>
                  <div className="flex gap-2">
                    <dt className="text-tinta-suave">Salida aplicada</dt>
                    <dd className="tabular-nums">{hour(shown.receipt.checkout_at)}</dd>
                  </div>
                  <div className="flex gap-2">
                    <dt className="text-tinta-suave">Versión de la reserva</dt>
                    <dd className="tabular-nums">{shown.receipt.version}</dd>
                  </div>
                </dl>
              </div>
            )}

            <h4 className="mt-4 border-t border-tinta-suave/20 pt-3 text-sm font-semibold">
              Llamadas del turno
            </h4>
            {loading && <p className="mt-1 text-xs text-tinta-suave">Cargando el registro.</p>}
            {!loading && traces.length === 0 && (
              <p className="mt-1 text-xs text-tinta-suave">
                Sin llamadas registradas en esta conversación.
              </p>
            )}
            {traces.length > 0 && (
              <ul className="mt-2 divide-y divide-tinta-suave/15">
                {traces.map((trace) => (
                  <li key={`${trace.created_at}-${trace.http_request_id ?? ""}`} className="py-2">
                    <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 text-xs tabular-nums">
                      <time className="text-tinta-suave">{dateTime(trace.created_at)}</time>
                      <span>{millis(trace.duration_ms)}</span>
                      <span>
                        {tokens(trace.prompt_tokens)} / {tokens(trace.completion_tokens)} tokens
                        simulados
                      </span>
                    </div>
                    {trace.http_request_id !== null && (
                      <p className="mt-0.5 break-all text-[11px] tabular-nums text-tinta-suave">
                        X-Request-ID {trace.http_request_id}
                      </p>
                    )}
                    {trace.detail !== null && (
                      <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap font-mono text-[11px] text-tinta-suave">
                        {JSON.stringify(trace.detail)}
                      </pre>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs text-tinta-suave">{label}</dt>
      <dd className="font-semibold tabular-nums">{value}</dd>
    </div>
  );
}
