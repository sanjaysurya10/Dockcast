import { type Horizon, HORIZON_OPTIONS, horizonLabel } from "@/lib/risk";

interface HorizonToggleProps {
  value: Horizon;
  onChange: (horizon: Horizon) => void;
}

/** Now · +30 · +60 · +120 as a radio group (PRD 16.3 item 4). */
export function HorizonToggle({ value, onChange }: HorizonToggleProps) {
  return (
    <fieldset className="inline-flex rounded-control border border-line bg-surface p-0.5 shadow-sm">
      <legend className="sr-only">Forecast horizon</legend>
      {HORIZON_OPTIONS.map((horizon) => {
        const id = `horizon-${horizon}`;
        const checked = value === horizon;
        return (
          <label
            key={horizon}
            htmlFor={id}
            className={`num inline-flex min-h-11 min-w-12 cursor-pointer items-center justify-center rounded-[6px] px-3 text-sm has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-brand ${
              checked ? "bg-brand text-surface" : "text-muted hover:text-ink"
            }`}
          >
            <input
              id={id}
              type="radio"
              name="horizon"
              className="sr-only"
              checked={checked}
              onChange={() => onChange(horizon)}
            />
            {horizonLabel(horizon)}
          </label>
        );
      })}
    </fieldset>
  );
}
