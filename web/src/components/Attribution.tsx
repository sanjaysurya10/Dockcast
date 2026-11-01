export function Attribution() {
  return (
    <footer className="border-t border-line bg-surface px-4 py-3 text-xs text-muted">
      Station data:{" "}
      <a
        className="underline hover:text-ink"
        href="https://data.smartdublin.ie/"
        target="_blank"
        rel="noreferrer"
      >
        Dublin City Council / Smart Dublin
      </a>{" "}
      (CC BY 4.0). Weather: Met Éireann (CC BY 4.0). Forecasts are estimates, not guarantees of
      availability.
    </footer>
  );
}
