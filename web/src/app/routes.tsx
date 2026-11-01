import type { RouteObject } from "react-router";

import { AboutPage } from "@/pages/AboutPage";
import { MapPage } from "@/pages/MapPage";
import { ModelPage } from "@/pages/ModelPage";
import { NotFoundPage } from "@/pages/NotFoundPage";
import { StationPage } from "@/pages/StationPage";

import { Layout } from "./Layout";

/** PRD 16.1 routes. */
export const routes: RouteObject[] = [
  {
    element: <Layout />,
    children: [
      { index: true, element: <MapPage /> },
      { path: "station/:stationKey", element: <StationPage /> },
      { path: "model", element: <ModelPage /> },
      { path: "about", element: <AboutPage /> },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
];
