export interface HSL {
  h: number; // 0-360
  s: number; // 0-100
  l: number; // 0-100
}

/**
 * Convert hex color string to HSL
 */
export function hexToHSL(hex: string): HSL {
  const r = parseInt(hex.slice(1, 3), 16) / 255;
  const g = parseInt(hex.slice(3, 5), 16) / 255;
  const b = parseInt(hex.slice(5, 7), 16) / 255;

  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const d = max - min;

  let h = 0;
  if (d !== 0) {
    if (max === r) h = ((g - b) / d) % 6;
    else if (max === g) h = (b - r) / d + 2;
    else h = (r - g) / d + 4;
    h = Math.round(h * 60);
    if (h < 0) h += 360;
  }

  const l = (max + min) / 2;
  const s = d === 0 ? 0 : d / (1 - Math.abs(2 * l - 1));

  return {
    h,
    s: Math.round(s * 100),
    l: Math.round(l * 100),
  };
}

export interface ThemePalette {
  light: Record<string, string>;
  dark: Record<string, string>;
}

/**
 * Generate a complete theme palette from a seed hex color.
 * Derives all CSS variable values for light and dark modes.
 */
export function generateThemePalette(seedHex: string): ThemePalette {
  const { h, s } = hexToHSL(seedHex);

  return {
    light: {
      "--color-primary": `${h} ${s}% 50%`,
      "--color-primary-hover": `${h} ${s}% 43%`,
      "--color-primary-active": `${h} ${s}% 37%`,
      "--color-primary-subtle": `${h} ${Math.max(s - 20, 10)}% 95%`,
      "--color-background": `${h} 15% 98%`,
      "--color-surface": `${h} 12% 100%`,
      "--color-surface-hover": `${h} 15% 96%`,
      "--color-border": `${h} 12% 90%`,
      "--color-border-subtle": `${h} 8% 94%`,
      "--color-text": `${h} 15% 12%`,
      "--color-text-secondary": `${h} 10% 40%`,
      "--color-text-muted": `${h} 8% 55%`,
      "--color-text-on-primary": `0 0% 100%`,
      "--chart-1": `${h} ${s}% 55%`,
      "--chart-2": `${(h + 40) % 360} ${Math.max(s - 10, 15)}% 55%`,
      "--chart-3": `${(h - 40 + 360) % 360} ${Math.max(s - 10, 15)}% 55%`,
      "--chart-4": `${(h + 80) % 360} ${Math.max(s - 15, 15)}% 55%`,
      "--chart-5": `${(h - 80 + 360) % 360} ${Math.max(s - 15, 15)}% 55%`,
      "--chart-neutral": `${h} 10% 60%`,
    },
    dark: {
      "--color-primary": `${h} ${Math.max(s - 5, 10)}% 60%`,
      "--color-primary-hover": `${h} ${Math.max(s - 5, 10)}% 67%`,
      "--color-primary-active": `${h} ${Math.max(s - 5, 10)}% 73%`,
      "--color-primary-subtle": `${h} ${Math.max(s - 25, 10)}% 15%`,
      "--color-background": `${h} 12% 7%`,
      "--color-surface": `${h} 10% 11%`,
      "--color-surface-hover": `${h} 12% 15%`,
      "--color-border": `${h} 10% 18%`,
      "--color-border-subtle": `${h} 8% 14%`,
      "--color-text": `${h} 10% 93%`,
      "--color-text-secondary": `${h} 8% 65%`,
      "--color-text-muted": `${h} 6% 48%`,
      "--color-text-on-primary": `${h} 15% 10%`,
      "--chart-1": `${h} ${s}% 65%`,
      "--chart-2": `${(h + 40) % 360} ${Math.max(s - 10, 15)}% 65%`,
      "--chart-3": `${(h - 40 + 360) % 360} ${Math.max(s - 10, 15)}% 65%`,
      "--chart-4": `${(h + 80) % 360} ${Math.max(s - 15, 15)}% 65%`,
      "--chart-5": `${(h - 80 + 360) % 360} ${Math.max(s - 15, 15)}% 65%`,
      "--chart-neutral": `${h} 10% 50%`,
    },
  };
}

/**
 * Read a CSS variable from :root and return as hsl() string for ECharts usage
 */
export function getCSSColorVar(name: string): string {
  const value = getComputedStyle(document.documentElement)
    .getPropertyValue(name)
    .trim();
  return `hsl(${value})`;
}

/**
 * Get ECharts color palette from current CSS variables
 */
export function getEChartsColors(): string[] {
  return [
    getCSSColorVar("--chart-1"),
    getCSSColorVar("--chart-2"),
    getCSSColorVar("--chart-3"),
    getCSSColorVar("--chart-4"),
    getCSSColorVar("--chart-5"),
  ];
}

/**
 * Get emotion-specific colors (fixed semantic colors)
 */
export function getEmotionColors() {
  return {
    positive: getCSSColorVar("--chart-positive"),
    negative: getCSSColorVar("--chart-negative"),
    neutral: getCSSColorVar("--chart-neutral"),
  };
}
