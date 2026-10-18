import { useEffect, useState } from "react";
import { API_BASE_URL, checkHealth } from "./api";
import GuestView from "./GuestView";
import ManagerView from "./ManagerView";
import {
  defaultToken,
  findSession,
  loadToken,
  saveToken,
  sessionFor,
  sessionsOf,
  type Role,
} from "./sessions";

// La sesion guardada puede venir de un kit anterior: si el codigo ya no existe o
// el rol no coincide, se cae a la primera del rol.
function initialToken(role: Role): string {
  const stored = loadToken(role);
  if (stored !== null && findSession(stored)?.role === role) return stored;
  return defaultToken(role);
}

type Health = "checking" | "ok" | "down";

export default function App() {
  const [tokens, setTokens] = useState<Record<Role, string>>(() => ({
    guest: initialToken("guest"),
    manager: initialToken("manager"),
  }));
  const [tab, setTab] = useState<Role>("guest");
  const [health, setHealth] = useState<Health>("checking");

  useEffect(() => {
    let alive = true;
    checkHealth()
      .then(() => {
        if (alive) setHealth("ok");
      })
      .catch(() => {
        if (alive) setHealth("down");
      });
    return () => {
      alive = false;
    };
  }, []);

  const session = sessionFor(tab, tokens[tab]);

  function choose(role: Role, token: string) {
    setTokens((prev) => ({ ...prev, [role]: token }));
    saveToken(role, token);
  }

  return (
    <div className="min-h-screen">
      <header className="border-b border-tinta-suave/25 bg-white">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3 px-4 pt-4">
          <div className="flex flex-wrap items-baseline gap-3">
            <h1 className="text-lg font-bold tracking-tight">Una salida más tarde</h1>
            <span className="text-xs text-tinta-suave">Mostrador de recepción</span>
          </div>
          <HealthLine health={health} />
        </div>

        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3 px-4 py-3">
          <div role="tablist" className="flex gap-0.5 rounded-sello border border-tinta-suave/30 p-0.5">
            {(["guest", "manager"] as Role[]).map((role) => (
              <button
                key={role}
                role="tab"
                aria-selected={tab === role}
                onClick={() => setTab(role)}
                className={`rounded-sello px-3 py-1 text-sm font-semibold ${
                  tab === role ? "bg-tinta text-white" : "text-tinta-suave hover:text-tinta"
                }`}
              >
                {role === "guest" ? "Huésped" : "Responsable"}
              </button>
            ))}
          </div>

          <SessionPicker role={tab} value={session.token} onChange={(token) => choose(tab, token)} />
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-4 py-6">
        {tab === "guest" ? (
          <GuestView key={session.token} session={session} />
        ) : (
          <ManagerView key={session.token} session={session} />
        )}
      </main>
    </div>
  );
}

function SessionPicker({
  role,
  value,
  onChange,
}: {
  role: Role;
  value: string;
  onChange: (token: string) => void;
}) {
  return (
    <label className="flex items-center gap-2 text-xs text-tinta-suave">
      Sesión de demostración
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="rounded-sello border border-tinta-suave/40 bg-white px-2 py-1 text-sm text-tinta"
      >
        {sessionsOf(role).map((item) => (
          <option key={item.token} value={item.token}>
            {item.name} ({item.stayId ?? item.hotelId})
          </option>
        ))}
      </select>
    </label>
  );
}

function HealthLine({ health }: { health: Health }) {
  if (health === "ok") {
    return <span className="text-xs text-sal">Backend conectado</span>;
  }
  if (health === "down") {
    return (
      <span className="text-xs text-coral">
        Sin respuesta del backend en {API_BASE_URL}. Arráncalo con uvicorn.
      </span>
    );
  }
  return <span className="text-xs text-tinta-suave">Comprobando el backend en {API_BASE_URL}</span>;
}
