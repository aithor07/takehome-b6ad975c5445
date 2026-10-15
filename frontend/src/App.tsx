import { useEffect, useState } from "react";
import { checkBackendHealth } from "./api";

export default function App() {
  const [backendStatus, setBackendStatus] = useState<string>("Conectando...");

  useEffect(() => {
    checkBackendHealth()
      .then((data) => setBackendStatus(data.status === "ok" ? "Online" : "Error"))
      .catch(() => setBackendStatus("Offline"));
  }, []);

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900 p-8">
      <div className="max-w-4xl mx-auto space-y-6">
        <header className="flex items-center justify-between border-b border-slate-200 pb-4">
          <div>
            <h1 className="text-2xl font-bold">Una salida más tarde</h1>
            <p className="text-sm text-slate-500">
              Gestión de peticiones de late check-out con IA y aprobación humana
            </p>
          </div>
          <span
            className={`px-3 py-1 rounded-full text-xs font-medium ${
              backendStatus === "Online"
                ? "bg-emerald-100 text-emerald-700"
                : "bg-red-100 text-red-700"
            }`}
          >
            Backend: {backendStatus}
          </span>
        </header>

        <main className="bg-white p-6 rounded-xl shadow-sm border border-slate-200">
          <p className="text-slate-600">
            Entorno listo. Esperando enunciado y paquete de datos...
          </p>
        </main>
      </div>
    </div>
  );
}