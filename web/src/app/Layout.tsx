import { NavLink, Outlet } from "react-router";

import { Attribution } from "@/components/Attribution";
import { FreshnessBanner } from "@/components/FreshnessBanner";

interface NavItem {
  to: string;
  label: string;
  end: boolean;
  /** Shown in the phone bottom bar instead of the header (PRD 16.6). */
  bottom: boolean;
}

const NAV: NavItem[] = [
  { to: "/nearby", label: "Nearby", end: false, bottom: true },
  { to: "/", label: "Map", end: true, bottom: true },
  { to: "/model", label: "Accuracy", end: false, bottom: true },
  { to: "/about", label: "About", end: false, bottom: false },
];

function linkClass(isActive: boolean): string {
  return `inline-flex min-h-11 items-center justify-center rounded-control px-3 text-sm ${
    isActive ? "bg-brand-tint font-medium text-brand-ink" : "text-muted hover:text-ink"
  }`;
}

/**
 * On phones the page is exactly one screen tall: header, content (scrolls on its own),
 * attribution and the bottom nav, so the map can fill the space between them.
 */
export function Layout() {
  return (
    <div className="flex h-dvh flex-col md:h-auto md:min-h-dvh">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-30 focus:rounded-control focus:bg-surface focus:px-3 focus:py-2"
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
              <li key={item.to} className={item.bottom ? "hidden md:block" : undefined}>
                <NavLink
                  to={item.to}
                  end={item.end}
                  className={({ isActive }) => linkClass(isActive)}
                >
                  {item.label}
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>
      </header>
      <FreshnessBanner />
      <main id="main" className="flex min-h-0 flex-1 flex-col overflow-y-auto md:overflow-visible">
        <Outlet />
      </main>
      <Attribution />
      <nav aria-label="Sections" className="border-t border-line bg-surface md:hidden">
        <ul className="grid grid-cols-3">
          {NAV.filter((item) => item.bottom).map((item) => (
            <li key={item.to}>
              <NavLink
                to={item.to}
                end={item.end}
                className={({ isActive }) => `${linkClass(isActive)} w-full rounded-none`}
              >
                {item.label}
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>
    </div>
  );
}
