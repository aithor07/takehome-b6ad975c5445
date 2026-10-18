import { BAND_FROM, BAND_TO, bandPosition, hour } from "./presentation";

type TimeBandProps = {
  currentIso: string | null;
  requestedIso: string | null;
};

// Banda del dia: marca la salida actual y la pedida, y pinta en coral el tramo
// que el huesped quiere correr. El limite del hotel no se deduce aqui, se cita
// con su documento justo al lado, porque esa cita es la fuente que lo respalda.
export default function TimeBand({ currentIso, requestedIso }: TimeBandProps) {
  const currentTime = hour(currentIso);
  const requestedTime = hour(requestedIso);
  const currentAt = bandPosition(currentTime);
  const requestedAt = bandPosition(requestedTime);

  const label =
    currentAt === null || requestedAt === null
      ? "Banda horaria del día"
      : `Salida actual ${currentTime}, salida pedida ${requestedTime}`;

  return (
    <div className="relative mt-3 h-16 select-none" role="img" aria-label={label}>
      <div className="absolute inset-x-0 top-7 h-px bg-tinta-suave/30" />
      <div className="absolute left-0 top-5 h-5 w-px bg-tinta-suave/40" />
      <div className="absolute right-0 top-5 h-5 w-px bg-tinta-suave/40" />
      <span className="absolute left-0 top-11 text-[10px] tabular-nums text-tinta-suave">
        {BAND_FROM}
      </span>
      <span className="absolute right-0 top-11 text-[10px] tabular-nums text-tinta-suave">
        {BAND_TO}
      </span>

      {/* Tramo que el huesped quiere correr */}
      {currentAt !== null && requestedAt !== null && requestedAt > currentAt && (
        <div
          className="absolute top-7 h-px bg-coral"
          style={{ left: `${currentAt}%`, width: `${requestedAt - currentAt}%` }}
        />
      )}

      {/* Salida actual */}
      {currentAt !== null && (
        <div
          className="absolute top-1 flex -translate-x-1/2 flex-col items-center"
          style={{ left: `${currentAt}%` }}
        >
          <span className="text-xs font-semibold tabular-nums">{currentTime}</span>
          <span className="mt-1.5 h-5 w-px bg-tinta-suave" />
        </div>
      )}

      {/* Salida pedida */}
      {requestedAt !== null && (
        <div
          className="absolute top-1 flex -translate-x-1/2 flex-col items-center"
          style={{ left: `${requestedAt}%` }}
        >
          <span className="text-xs font-semibold tabular-nums text-coral">{requestedTime}</span>
          <span className="mt-1.5 h-5 w-2 bg-coral" />
        </div>
      )}
    </div>
  );
}
