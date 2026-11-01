export type Rgb = [number, number, number];

const FALLBACK: Rgb = [124, 139, 132];

export function hexToRgb(hex: string): Rgb {
  const match = /^#?([0-9a-f]{6})$/i.exec(hex.trim());
  if (!match?.[1]) return FALLBACK;
  const value = parseInt(match[1], 16);
  return [(value >> 16) & 255, (value >> 8) & 255, value & 255];
}

/** A design token as RGB for WebGL layers; follows the active light/dark tokens. */
export function tokenRgb(name: string, element: Element = document.documentElement): Rgb {
  return hexToRgb(getComputedStyle(element).getPropertyValue(name));
}
