import type { ErrorAnalysis } from "@/api/client";

const DAY = 86_400_000;
const LEAD_DAYS = 14;

const DATE = new Intl.DateTimeFormat("en-IE", {
  timeZone: "Europe/Dublin",
  day: "numeric",
  month: "short",
});

/**
 * Rolling-origin backtest (PRD 13.1): each fold trains on everything before it, skips a
 * 120-min gap, then tests on the next week.
 */
export function FoldDiagram({ folds }: { folds: ErrorAnalysis["folds"] }) {
  if (folds.length === 0) return null;
  const start = Date.parse(folds[0]?.test_start ?? "") - LEAD_DAYS * DAY;
  const end = Math.max(...folds.map((fold) => Date.parse(fold.test_end)));
  const x = (iso: string) => ((Date.parse(iso) - start) / (end - start)) * 100;
  return (
    <figure className="space-y-2">
      <figcaption className="text-sm text-muted">
        {folds.length} folds. Each trains on all data before its test week (left, grey, earlier
        history not to scale), leaves a 2-hour gap, then is scored on the next 7 days (teal).
      </figcaption>
      <ol className="space-y-1.5" aria-label="Backtest folds">
        {folds.map((fold) => (
          <li key={fold.fold} className="flex items-center gap-3 text-xs">
            <span className="num w-12 shrink-0 text-muted">Fold {fold.fold}</span>
            <span className="relative h-4 flex-1" aria-hidden="true">
              <span
                className="absolute inset-y-0 left-0 rounded-l-[4px] bg-line"
                style={{ width: `${x(fold.train_end)}%` }}
              />
              <span
                className="absolute inset-y-0 rounded-[4px] bg-series-1"
                style={{ left: `${x(fold.test_start)}%`, width: `${x(fold.test_end) - x(fold.test_start)}%` }}
              />
            </span>
            <span className="num w-40 shrink-0 whitespace-nowrap text-muted">
              test {DATE.format(Date.parse(fold.test_start))}–{DATE.format(Date.parse(fold.test_end))}
            </span>
          </li>
        ))}
      </ol>
    </figure>
  );
}
