export function AboutPage() {
  return (
    <article className="max-w-prose space-y-4">
      <h1 className="text-2xl font-semibold">About DockCast</h1>
      <p>
        DockCast forecasts how many bikes each Dublin Bikes station will have in 30, 60 and 120
        minutes, with a likely range (P10–P90). Forecasts come from LightGBM quantile models trained
        on station history. They are checked with a rolling-origin backtest, so every number on the
        Accuracy page comes from data the model had not seen.
      </p>
      <p>
        The map also shows Lyon's Vélo'v stations to prove the multi-city design. Lyon has live
        status only: no model, no forecasts and no net flow.
      </p>
      <h2 className="text-lg font-semibold">Limitations</h2>
      <ul className="list-disc space-y-1 pl-5">
        <li>Forecasts are estimates, not guarantees of availability.</li>
        <li>Rebalancing vans are not observed directly and cause the largest errors.</li>
        <li>The served model does not use weather.</li>
        <li>Only dock counts are modelled; there is no trip data.</li>
      </ul>
      <h2 className="text-lg font-semibold">Data sources</h2>
      <ul className="list-disc space-y-1 pl-5">
        <li>
          Station status: Dublin City Council / Smart Dublin, licensed{" "}
          <a className="underline" href="https://creativecommons.org/licenses/by/4.0/">
            CC BY 4.0
          </a>
          .
        </li>
        <li>
          Lyon station status: JCDecaux (Vélo'v), licensed{" "}
          <a className="underline" href="https://developer.jcdecaux.com/files/Open-Licence-fr.pdf">
            Licence Ouverte (Etalab)
          </a>
          . Each station shows the time of its latest update.
        </li>
        <li>Weather: Met Éireann, licensed CC BY 4.0.</li>
      </ul>
    </article>
  );
}
