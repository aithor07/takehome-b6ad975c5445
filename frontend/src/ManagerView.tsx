import { useCallback, useEffect, useMemo, useState } from "react";
import {
  approveProposal,
  describeError,
  listProposals,
  reconcileProposal,
  rejectProposal,
  type DecisionResult,
  type Proposal,
} from "./api";
import {
  BUTTON_DANGER,
  BUTTON_PRIMARY,
  BUTTON_QUIET,
  canDecide,
  canReconcile,
  decisionTone,
  euros,
  hour,
  hourShift,
  needsReview,
  proposalBadge,
  shortId,
} from "./presentation";
import type { DemoSession } from "./sessions";
import ProposalDetail from "./ProposalDetail";

type ManagerViewProps = {
  session: DemoSession;
};

export default function ManagerView({ session }: ManagerViewProps) {
  const [proposals, setProposals] = useState<Proposal[]>([]);
  const [results, setResults] = useState<Record<string, DecisionResult>>({});
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [bulk, setBulk] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [actionOnly, setActionOnly] = useState(false);
  const [follow, setFollow] = useState(true);
  const [detail, setDetail] = useState<Proposal | null>(null);

  // Cadena de promesas: los cambios de estado quedan dentro de las callbacks, asi
  // la carga no provoca renders en cascada desde el efecto de arranque.
  const load = useCallback(
    () =>
      listProposals(session.token)
        .then((data) => {
          setProposals(data.proposals);
          setError(null);
          setLoading(false);
        })
        .catch((caught: unknown) => {
          setError(describeError(caught));
          setLoading(false);
        }),
    [session.token],
  );

  useEffect(() => {
    void load();
  }, [load]);

  // Las dos pantallas conviven: seguir los cambios hace que una solicitud recien
  // escrita por el huesped aparezca aqui sin tocar nada durante la demo. El
  // sondeo no enciende el aviso de "Actualizando".
  useEffect(() => {
    if (!follow) return;
    const timer = window.setInterval(() => void load(), 5000);
    return () => window.clearInterval(timer);
  }, [follow, load]);

  // Refresco a mano: aqui si se avisa, porque lo ha pedido una persona.
  function refresh() {
    setLoading(true);
    void load();
  }

  async function act(
    id: string,
    call: (token: string, proposalId: string) => Promise<DecisionResult>,
  ) {
    setBusyId(id);
    try {
      const result = await call(session.token, id);
      setResults((prev) => ({ ...prev, [id]: result }));
      setError(null);
      await load();
    } catch (caught) {
      setError(describeError(caught));
    } finally {
      setBusyId(null);
    }
  }

  const decidables = proposals.filter((item) => canDecide(item.status));
  const uncertain = proposals.filter((item) => canReconcile(item.status));
  const revisables = proposals.filter((item) => needsReview(item.status));

  const visible = useMemo(
    () =>
      actionOnly
        ? proposals.filter(
            (item) =>
              canDecide(item.status) || canReconcile(item.status) || needsReview(item.status),
          )
        : proposals,
    [actionOnly, proposals],
  );

  // Comprobar pendientes de una vez: el enunciado lo pide como accion propia y
  // en la demo se ve como cada operacion incierta pasa a confirmada.
  async function reconcileAll() {
    setBulk(true);
    setError(null);
    for (const proposal of uncertain) {
      try {
        const result = await reconcileProposal(session.token, proposal.id);
        setResults((prev) => ({ ...prev, [proposal.id]: result }));
      } catch (caught) {
        setError(describeError(caught));
      }
    }
    setBulk(false);
    await load();
  }

  return (
    <section className="rounded-sello border border-tinta-suave/25 bg-white">
      <header className="border-b border-tinta-suave/20 px-4 py-3">
        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <div className="flex flex-wrap items-baseline gap-3">
            <h2 className="text-sm font-semibold">Propuestas del hotel</h2>
            <span className="text-xs tabular-nums text-tinta-suave">{session.hotelId}</span>
          </div>
          <span className="text-xs tabular-nums text-tinta-suave">
            {loading ? "Actualizando" : `${proposals.length} en total`}
          </span>
        </div>

        <dl className="mt-2 flex flex-wrap items-baseline gap-x-5 gap-y-1">
          <Counter label="pendientes de aprobación" value={decidables.length} />
          <Counter label="sin confirmar" value={uncertain.length} />
          <Counter label="para revisar" value={revisables.length} />
        </dl>

        <div className="mt-3 flex flex-wrap items-center gap-3">
          {uncertain.length > 0 && (
            <button
              type="button"
              onClick={() => void reconcileAll()}
              disabled={bulk}
              className={BUTTON_QUIET}
            >
              Comprobar sin confirmar
            </button>
          )}
          <label className="flex items-center gap-1.5 text-xs text-tinta-suave">
            <input
              type="checkbox"
              checked={actionOnly}
              onChange={(event) => setActionOnly(event.target.checked)}
              className="accent-tinta"
            />
            Solo lo que requiere acción
          </label>
          <label className="flex items-center gap-1.5 text-xs text-tinta-suave">
            <input
              type="checkbox"
              checked={follow}
              onChange={(event) => setFollow(event.target.checked)}
              className="accent-tinta"
            />
            Seguir cambios cada 5 s
          </label>
          <button type="button" onClick={refresh} className={BUTTON_QUIET}>
            Actualizar
          </button>
        </div>
      </header>

      {error !== null && (
        <p className="border-b border-coral/40 bg-coral/5 px-4 py-2 text-sm text-coral">{error}</p>
      )}

      {proposals.length === 0 ? (
        <p className="px-4 py-6 text-sm text-tinta-suave">
          No hay propuestas en este hotel todavía. En cuanto un huésped pida una hora de salida,
          aparecerá aquí con su documento y su importe.
        </p>
      ) : visible.length === 0 ? (
        <p className="px-4 py-6 text-sm text-tinta-suave">
          Nada requiere acción ahora mismo. Quita el filtro para ver las propuestas cerradas.
        </p>
      ) : (
        <ul className="divide-y divide-tinta-suave/20">
          {visible.map((proposal) => (
            <ProposalRow
              key={proposal.id}
              proposal={proposal}
              result={results[proposal.id]}
              busy={busyId === proposal.id}
              onAct={act}
              onOpen={() => setDetail(proposal)}
            />
          ))}
        </ul>
      )}

      {detail !== null && (
        <ProposalDetail
          session={session}
          proposal={detail}
          onClose={() => {
            setDetail(null);
            void load();
          }}
        />
      )}
    </section>
  );
}

type ProposalRowProps = {
  proposal: Proposal;
  result: DecisionResult | undefined;
  busy: boolean;
  onAct: (
    id: string,
    call: (token: string, proposalId: string) => Promise<DecisionResult>,
  ) => Promise<void>;
  onOpen: () => void;
};

function ProposalRow({ proposal, result, busy, onAct, onOpen }: ProposalRowProps) {
  const badge = proposalBadge(proposal.status);

  return (
    <li className="px-4 py-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
          <span className="text-sm font-semibold tabular-nums">{proposal.stay_id}</span>
          <span
            className="text-sm font-semibold tabular-nums"
            aria-label={`Salida actual ${hour(proposal.current_checkout_at)}, salida pedida ${hour(proposal.requested_checkout_at)}`}
          >
            <span aria-hidden="true">
              {hour(proposal.current_checkout_at)}
              <span className="px-1 font-normal text-tinta-suave">→</span>
              {hour(proposal.requested_checkout_at)}
            </span>
          </span>
          <span className="text-sm tabular-nums">{euros(proposal.fee_eur)}</span>
          <span className="text-xs tabular-nums text-tinta-suave">
            {hourShift(proposal.current_checkout_at, proposal.requested_checkout_at)}
          </span>
        </div>
        <span className={badge.className}>{badge.label}</span>
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs tabular-nums text-tinta-suave">
        <span>
          {proposal.policy_document_id} versión {proposal.policy_version}
        </span>
        <span>operación {shortId(proposal.operation_key)}</span>
        {proposal.receipt !== null && <span>confirmación {shortId(proposal.receipt.change_id)}</span>}
      </div>

      {needsReview(proposal.status) && (
        <p className="mt-2 text-sm text-coral">
          Los datos cambiaron y el cambio no se hizo. El huésped tiene que pedirlo de nuevo.
        </p>
      )}

      {result !== undefined && (
        <p className={`mt-2 text-sm ${decisionTone(result.httpStatus)}`}>
          {result.decision.message}
          <span className="ml-2 text-[11px]">HTTP {result.httpStatus}</span>
        </p>
      )}

      <div className="mt-2 flex flex-wrap gap-2">
        {canDecide(proposal.status) && (
          <>
            <button
              type="button"
              disabled={busy}
              onClick={() => void onAct(proposal.id, approveProposal)}
              className={BUTTON_PRIMARY}
            >
              Aprobar
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => void onAct(proposal.id, rejectProposal)}
              className={BUTTON_DANGER}
            >
              Rechazar
            </button>
          </>
        )}
        {canReconcile(proposal.status) && (
          <button
            type="button"
            disabled={busy}
            onClick={() => void onAct(proposal.id, reconcileProposal)}
            className={BUTTON_QUIET}
          >
            Comprobar
          </button>
        )}
        <button type="button" onClick={onOpen} className={BUTTON_QUIET}>
          Detalle
        </button>
      </div>
    </li>
  );
}

function Counter({ label, value }: { label: string; value: number }) {
  return (
    <div className="flex items-baseline gap-1">
      <dd className="text-sm font-semibold tabular-nums">{value}</dd>
      <dt className="text-xs text-tinta-suave">{label}</dt>
    </div>
  );
}
