import { STATE_LABEL, type StationState } from "@/lib/status";

const STYLE: Record<StationState, string> = {
  empty: "bg-risk-empty-tint text-risk-empty-ink",
  full: "bg-risk-full-tint text-risk-full-ink",
  ok: "bg-brand-tint text-brand-ink",
  closed: "bg-ground text-muted border border-line",
  unknown: "bg-ground text-muted border border-line",
};

export function StateBadge({ state }: { state: StationState }) {
  return (
    <span
      className={`inline-flex items-center rounded-control px-2 py-0.5 text-xs font-medium ${STYLE[state]}`}
    >
      {STATE_LABEL[state]}
    </span>
  );
}
