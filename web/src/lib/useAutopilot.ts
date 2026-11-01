import { useCallback, useEffect, useRef, useState } from "react";

import type { RiskStation } from "@/api/client";

import { AUTOPILOT_FLY_MS, AUTOPILOT_HOLD_MS, USER_INPUTS } from "./autopilot";

/** Mark the autopilot's own controls so pressing them toggles instead of counting as input. */
export const AUTOPILOT_CONTROL = "data-autopilot-control";

interface AutopilotOptions {
  stops: RiskStation[];
  reducedMotion: boolean;
  onVisit: (stop: RiskStation) => void;
}

export interface Autopilot {
  active: boolean;
  /** Position in the tour (0-based) while active. */
  index: number;
  current: RiskStation | null;
  start: () => void;
  stop: () => void;
}

/**
 * Tour loop (PRD 16.3 item 7): visit a stop, fly 2 s, hold 4 s, next, wrapping. Any pointer,
 * wheel, touch or key input outside the autopilot controls stops it. With reduced motion the
 * map jumps, so only the hold remains.
 */
export function useAutopilot({ stops, reducedMotion, onVisit }: AutopilotOptions): Autopilot {
  const [active, setActive] = useState(false);
  const [index, setIndex] = useState(0);
  const stopsRef = useRef(stops);
  const visitRef = useRef(onVisit);
  useEffect(() => {
    stopsRef.current = stops;
    visitRef.current = onVisit;
  });

  const stop = useCallback(() => setActive(false), []);
  const start = useCallback(() => {
    if (stopsRef.current.length === 0) return;
    setIndex(0);
    setActive(true);
  }, []);

  useEffect(() => {
    if (!active) return;
    const tour = stopsRef.current;
    const here = tour[index % Math.max(tour.length, 1)];
    if (!here) {
      setActive(false);
      return;
    }
    visitRef.current(here);
    const dwell = (reducedMotion ? 0 : AUTOPILOT_FLY_MS) + AUTOPILOT_HOLD_MS;
    const timer = window.setTimeout(() => setIndex((i) => (i + 1) % tour.length), dwell);
    return () => window.clearTimeout(timer);
  }, [active, index, reducedMotion]);

  useEffect(() => {
    if (!active) return;
    const onInput = (event: Event) => {
      const target = event.target;
      if (target instanceof Element && target.closest(`[${AUTOPILOT_CONTROL}]`)) return;
      setActive(false);
    };
    USER_INPUTS.forEach((name) => window.addEventListener(name, onInput, { capture: true }));
    return () =>
      USER_INPUTS.forEach((name) => window.removeEventListener(name, onInput, { capture: true }));
  }, [active]);

  const current = active ? (stops[index % Math.max(stops.length, 1)] ?? null) : null;
  return { active, index, current, start, stop };
}
