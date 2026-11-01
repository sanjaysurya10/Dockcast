import { Outlet, type RouteObject } from "react-router";

import { AboutPage } from "@/pages/AboutPage";
import { MapPage } from "@/pages/MapPage";
import { ModelPage } from "@/pages/ModelPage";
import { NotFoundPage } from "@/pages/NotFoundPage";
import { StationPage } from "@/pages/StationPage";

import { Layout } from "./Layout";

/** Text pages get a centred column; the map page is full-bleed. */
function Contained() {
  return (
    <div className="mx-auto w-full max-w-5xl px-4 py-6">
      <Outlet />
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
          { path: "about", element: <AboutPage /> },
          { path: "*", element: <NotFoundPage /> },
        ],
      },
    ],
  },
];
