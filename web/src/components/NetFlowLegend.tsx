import type { NetFlowSummary } from "@/lib/netflow";
import { dublinTime } from "@/lib/status";

interface NetFlowLegendProps {
  summary: NetFlowSummary;
  windowMin: number;
  ts: string;
}

/** Explains the rings: net change in bikes, not trips (PRD 10.6, 16.3 item 8). */
export function NetFlowLegend({ summary, windowMin, ts }: NetFlowLegendProps) {
  return (
    <div
      className="rounded-card border border-line bg-surface/95 p-3 text-xs shadow-sm"
      data-testid="net-flow-legend"
    >
      <p className="mb-1 font-medium">
        Net flow, last {windowMin} min (to {dublinTime(ts)})
      </p>
      <ul className="space-y-1">
        <li className="flex items-center gap-2">
          <span
            aria-hidden="true"
            className="inline-block size-3 rounded-full border-2 border-brand"
          />
          <span className="flex-1">More bikes (inflow), ring grows</span>
          <span className="num text-muted">{summary.inflow}</span>
        </li>
        <li className="flex items-center gap-2">
          <span
            aria-hidden="true"
            className="inline-block size-3 rounded-full border-2 border-muted"
          />
          <span className="flex-1">Fewer bikes (outflow), ring shrinks</span>
          <span className="num text-muted">{summary.outflow}</span>
        </li>
        <li className="flex items-center gap-2">
          <span aria-hidden="true" className="inline-block size-3" />
          <span className="flex-1">No change</span>
          <span className="num text-muted">{summary.unchanged}</span>
        </li>
        <li className="flex items-center gap-2">
          <span aria-hidden="true" className="inline-block size-3" />
          <span className="flex-1">Excluded (rebalancing, closed or no data)</span>
          <span className="num text-muted">{summary.excluded}</span>
        </li>
      </ul>
      <p className="mt-2 text-muted">
        Net change in bikes at each station, not trips: arrivals and departures that cancel out are
        invisible. Ring size grows with the change.
      </p>
    </div>
  );
}
