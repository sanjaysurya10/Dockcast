import { useHealth } from "@/api/queries";
import { dublinTimeOrDate, isStale } from "@/lib/status";

/** "Live data delayed" when the collector's last run is over 5 min old (PRD 16.3 item 10). */
export function FreshnessBanner() {
  const health = useHealth();
  if (!health.data) return null;
  const lastRun = health.data.last_collector_run;
  if (!isStale(lastRun)) return null;
  return (
    <div
      role="status"
      aria-live="polite"
      className="bg-risk-empty-tint px-4 py-2 text-sm text-risk-empty-ink"
    >
      Live data delayed{lastRun ? ` (last update ${dublinTimeOrDate(lastRun)})` : ""}.
    </div>
  );
}
