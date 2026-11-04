import { lazy, Suspense } from "react";
import { Outlet, type RouteObject } from "react-router";

import { Loading } from "@/components/QueryState";

import { Layout } from "./Layout";

// Every page is its own chunk, so the first load only fetches the page it shows (PRD 16.8);
// chart pages also keep Recharts out of the other pages.
const MapPage = lazy(async () => ({ default: (await import("@/pages/MapPage")).MapPage }));
const NearbyPage = lazy(async () => ({
  default: (await import("@/pages/NearbyPage")).NearbyPage,
}));
const AboutPage = lazy(async () => ({ default: (await import("@/pages/AboutPage")).AboutPage }));
const NotFoundPage = lazy(async () => ({
  default: (await import("@/pages/NotFoundPage")).NotFoundPage,
}));
const StationPage = lazy(async () => ({
  default: (await import("@/pages/StationPage")).StationPage,
}));
const ModelPage = lazy(async () => ({ default: (await import("@/pages/ModelPage")).ModelPage }));

/** Text pages get a centred column; the map page is full-bleed. */
function Contained() {
  return (
    <div className="mx-auto w-full max-w-5xl px-4 py-6">
      <Suspense fallback={<Loading label="the page" />}>
        <Outlet />
      </Suspense>
    </div>
  );
}

/** PRD 16.1 routes. */
export const routes: RouteObject[] = [
  {
    element: <Layout />,
    children: [
      {
        index: true,
        element: (
          <Suspense fallback={<Loading label="the map" />}>
            <MapPage />
          </Suspense>
        ),
      },
      {
        element: <Contained />,
        children: [
          { path: "station/:stationKey", element: <StationPage /> },
          { path: "model", element: <ModelPage /> },
          { path: "nearby", element: <NearbyPage /> },
          { path: "about", element: <AboutPage /> },
          { path: "*", element: <NotFoundPage /> },
        ],
      },
    ],
  },
];
