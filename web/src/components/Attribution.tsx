import type { City } from "@/api/client";
import { useCities } from "@/api/queries";

/** Shown until `/v1/cities` answers, and if it fails. */
const DUBLIN: Pick<City, "city_code" | "attribution" | "source_url" | "licence_name"> = {
  city_code: "dublin",
  attribution: "Dublin City Council / Smart Dublin",
  source_url: "https://data.smartdublin.ie/",
  licence_name: "CC BY 4.0",
};

/** Credits every city's station data (from its config, M20) plus the weather source. */
export function Attribution() {
  const cities = useCities();
  const credited = (cities.data ?? [DUBLIN]).filter((city) => city.attribution);
  return (
    <footer className="border-t border-line bg-surface px-4 py-3 text-xs text-muted">
      Station data:{" "}
      {credited.map((city, index) => (
        <span key={city.city_code}>
          {index > 0 && "; "}
          <a
            className="underline hover:text-ink"
            href={city.source_url}
            target="_blank"
            rel="noreferrer"
          >
            {city.attribution}
          </a>{" "}
          ({city.licence_name})
        </span>
      ))}
      . Weather: Met Éireann (CC BY 4.0). Forecasts are estimates, not guarantees of availability.
    </footer>
  );
}
