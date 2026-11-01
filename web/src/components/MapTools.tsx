import { AUTOPILOT_CONTROL } from "@/lib/useAutopilot";

interface MapToolsProps {
  netFlowOn: boolean;
  onNetFlow: (on: boolean) => void;
  autopilotOn: boolean;
  autopilotStops: number;
  onAutopilot: () => void;
}

const BUTTON =
  "inline-flex min-h-11 items-center rounded-control border px-3 text-sm shadow-sm disabled:cursor-not-allowed disabled:opacity-60";

function tone(on: boolean): string {
  return on
    ? "border-brand bg-brand text-surface"
    : "border-line bg-surface text-ink hover:border-brand";
}

/** Net flow layer and autopilot toggles (PRD 16.3 items 7-8). */
export function MapTools(props: MapToolsProps) {
  const { netFlowOn, onNetFlow, autopilotOn, autopilotStops, onAutopilot } = props;
  const noStops = autopilotStops === 0 && !autopilotOn;
  return (
    <div className="flex flex-wrap gap-2">
      <button
        type="button"
        aria-pressed={netFlowOn}
        className={`${BUTTON} ${tone(netFlowOn)}`}
        onClick={() => onNetFlow(!netFlowOn)}
      >
        Net flow
      </button>
      <button
        type="button"
        aria-pressed={autopilotOn}
        disabled={noStops}
        title={noStops ? "No stations at risk at this horizon" : undefined}
        className={`${BUTTON} ${tone(autopilotOn)}`}
        onClick={onAutopilot}
        {...{ [AUTOPILOT_CONTROL]: "" }}
      >
        {autopilotOn ? "Stop autopilot" : "Autopilot"}
      </button>
    </div>
  );
}
