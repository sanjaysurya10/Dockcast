import { type Horizon, MAP_STATE_TOKENS, type MapState, type MapStation, stateLabel } from "@/lib/risk";

const NOW_STATES: MapState[] = ["empty", "full", "ok", "closed", "unknown"];
const FORECAST_STATES: MapState[] = [
  "empty",
  "empty-possible",
  "full",
  "full-possible",
  "ok",
  "unknown",
];

/** Colour key with counts, so identity is never colour alone (PRD 16.7). */
export function Legend({ stations, horizon }: { stations: MapStation[]; horizon: Horizon }) {
  const counts = new Map<MapState, number>();
  for (const station of stations) counts.set(station.state, (counts.get(station.state) ?? 0) + 1);
  const states = horizon === "now" ? NOW_STATES : FORECAST_STATES;
  return (
    <div className="rounded-card border border-line bg-surface/95 p-3 text-xs shadow-sm">
      <p className="mb-1 font-medium">
        {horizon === "now" ? "Now" : `At +${horizon} min, from the forecast range`}
      </p>
      <ul className="space-y-1" data-testid="legend">
        {states.map((state) => (
          <li key={state} className="flex items-center gap-2" data-state={state}>
            <span
              aria-hidden="true"
              className="inline-block size-3 rounded-full border-2"
              style={{
                background: `var(${MAP_STATE_TOKENS[state].fill})`,
                borderColor: `var(${
                  MAP_STATE_TOKENS[state].line === "--surface"
                    ? MAP_STATE_TOKENS[state].fill
                    : MAP_STATE_TOKENS[state].line
                })`,
              }}
            />
            <span className="flex-1">{stateLabel(state, horizon)}</span>
            <span className="num text-muted">{counts.get(state) ?? 0}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
