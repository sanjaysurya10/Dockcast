import { useDrivers } from "@/api/queries";
import { topDrivers } from "@/lib/drivers";

/** Top 4 feature groups behind the +60 median forecast (PRD 16.4), from TreeSHAP. */
export function DriverChips({ stationKey }: { stationKey: number }) {
  const drivers = useDrivers(stationKey, 60);
  return (
    <section aria-labelledby="drivers-heading" className="space-y-2">
      <h2 id="drivers-heading" className="text-lg font-semibold">
        What drives this forecast
      </h2>
      {drivers.isPending && (
        <p role="status" className="text-sm text-muted">
          Loading…
        </p>
      )}
      {drivers.isError && (
        <p className="text-sm text-muted">No explanation is available for this forecast yet.</p>
      )}
      {drivers.data && (
        <>
          <ul className="flex flex-wrap gap-2">
            {topDrivers(drivers.data).map((chip) => (
              <li
                key={chip.group}
                className="inline-flex items-center gap-2 rounded-control border border-line bg-surface px-3 py-1.5 text-sm"
              >
                <span aria-hidden="true" className="text-brand-ink">
                  {chip.direction === "up" ? "↑" : "↓"}
                </span>
                <span>{chip.label}</span>
                <span className="num text-muted">
                  {chip.direction === "up" ? "+" : "−"}
                  {Math.abs(chip.bikes).toFixed(1)}
                  <span className="sr-only">
                    {" "}
                    bikes {chip.direction === "up" ? "more" : "fewer"}
                  </span>
                </span>
              </li>
            ))}
          </ul>
          <p className="text-xs text-muted">
            How much each group of inputs moved the median forecast for +60 min, in bikes, measured
            with TreeSHAP. They add up to the raw forecast before it is kept between 0 and the
            number of docks.
          </p>
        </>
      )}
    </section>
  );
}
