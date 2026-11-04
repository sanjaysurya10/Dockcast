import { type ReactNode, useEffect, useRef, useState } from "react";

/**
 * Renders `children` once their slot comes within `margin` of the viewport, so heavy charts
 * below the fold do not block the first paint. `minHeight` reserves the space meanwhile.
 */
export function WhenVisible({
  children,
  minHeight,
  margin = "300px",
}: {
  children: ReactNode;
  minHeight: number;
  margin?: string;
}) {
  const slot = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(() => typeof IntersectionObserver === "undefined");
  useEffect(() => {
    const element = slot.current;
    if (visible || !element) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) setVisible(true);
      },
      { rootMargin: margin },
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, [visible, margin]);
  return visible ? <>{children}</> : <div ref={slot} style={{ minHeight }} aria-hidden="true" />;
}
