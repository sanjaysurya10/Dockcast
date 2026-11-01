import { NavLink, Outlet } from "react-router";

import { Attribution } from "@/components/Attribution";
import { FreshnessBanner } from "@/components/FreshnessBanner";

const NAV = [
  { to: "/", label: "Map", end: true },
  { to: "/model", label: "Accuracy", end: false },
  { to: "/about", label: "About", end: false },
];

export function Layout() {
  return (
    <div className="flex min-h-dvh flex-col">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-10 focus:rounded-control focus:bg-surface focus:px-3 focus:py-2"
      >
        Skip to content
      </a>
      <header className="flex items-center justify-between gap-4 border-b border-line bg-surface px-4 py-2">
        <NavLink to="/" className="text-lg font-semibold text-brand-ink">
          DockCast
        </NavLink>
        <nav aria-label="Main">
          <ul className="flex gap-1">
            {NAV.map((item) => (
              <li key={item.to}>
                <NavLink
                  to={item.to}
                  end={item.end}
                  className={({ isActive }) =>
                    `inline-flex min-h-11 items-center rounded-control px-3 text-sm ${
                      isActive ? "bg-brand-tint font-medium text-brand-ink" : "text-muted hover:text-ink"
                    }`
                  }
                >
                  {item.label}
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>
      </header>
      <FreshnessBanner />
      <main id="main" className="flex flex-1 flex-col">
        <Outlet />
      </main>
      <Attribution />
    </div>
  );
}
