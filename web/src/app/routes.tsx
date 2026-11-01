import { lazy, Suspense } from "react";
import { Outlet, type RouteObject } from "react-router";

import { Loading } from "@/components/QueryState";
import { AboutPage } from "@/pages/AboutPage";
import { MapPage } from "@/pages/MapPage";
import { NearbyPage } from "@/pages/NearbyPage";
import { NotFoundPage } from "@/pages/NotFoundPage";

import { Layout } from "./Layout";

// Chart pages load Recharts on demand, keeping it out of the initial bundle (PRD 16.8).
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
      { index: true, element: <MapPage /> },
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
