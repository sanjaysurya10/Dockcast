import type { ReactNode } from "react";

interface BottomSheetProps {
  label: string;
  expanded: boolean;
  onToggle: () => void;
  children: ReactNode;
}

/**
 * Phone: a sheet over the bottom of the map that peeks (handle and search) or opens to about
 * half the map (PRD 16.6). From the md breakpoint it is the fixed side panel.
 */
export function BottomSheet({ label, expanded, onToggle, children }: BottomSheetProps) {
  return (
    <aside
      aria-label={label}
      data-expanded={expanded}
      className={`absolute inset-x-0 bottom-0 z-10 flex flex-col rounded-t-card border-t border-line bg-surface shadow-[0_-4px_16px_rgb(0_0_0/0.12)] motion-safe:transition-[height] motion-safe:duration-200 md:static md:h-auto md:max-h-[calc(100dvh-7.5rem)] md:w-[24rem] md:rounded-none md:border-l md:border-t-0 md:shadow-none ${
        expanded ? "h-[55%]" : "h-36"
      }`}
    >
      <button
        type="button"
        aria-expanded={expanded}
        onClick={onToggle}
        className="flex min-h-11 w-full shrink-0 flex-col items-center justify-center gap-1 text-xs text-muted md:hidden"
      >
        <span aria-hidden="true" className="h-1 w-10 rounded-full bg-line" />
        {expanded ? `Collapse ${label.toLowerCase()}` : `Expand ${label.toLowerCase()}`}
      </button>
      <div className="min-h-0 flex-1 space-y-6 overflow-y-auto px-4 pb-4 md:p-4">{children}</div>
    </aside>
  );
}
