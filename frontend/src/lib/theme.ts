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
 * 首页需要纯白底，但 Hero 与按钮区仍应保持原本的 Indigo 强调色，
 * 因此单独提供一套首页变量：背景保持纯白，交互色回到默认主题的紫蓝体系。
 */
export function generateHomeThemePalette(): ThemePalette {
  return {
    light: {
      "--primary": "239 84% 50%",
      "--primary-hover": "239 84% 43%",
      "--primary-active": "239 84% 37%",
      "--primary-subtle": "239 70% 90%",
      "--background": "0 0% 100%",
      "--surface": "0 0% 100%",
      "--surface-hover": "0 0% 98%",
      "--border": "239 18% 90%",
      "--border-subtle": "239 16% 94%",
      "--text": "0 0% 8%",
      "--text-secondary": "0 0% 28%",
      "--text-muted": "0 0% 44%",
      "--text-on-primary": "0 0% 100%",
      "--chart-1": "239 84% 55%",
      "--chart-2": "279 74% 55%",
      "--chart-3": "199 74% 55%",
      "--chart-4": "319 69% 55%",
      "--chart-5": "159 69% 55%",
      "--chart-neutral": "0 0% 60%",
    },
    dark: {
      "--primary": "239 82% 74%",
      "--primary-hover": "239 86% 80%",
      "--primary-active": "239 76% 68%",
      "--primary-subtle": "239 28% 18%",
      "--background": "0 0% 6%",
      "--surface": "0 0% 9%",
      "--surface-hover": "0 0% 12%",
      "--border": "239 12% 22%",
      "--border-subtle": "239 10% 16%",
      "--text": "0 0% 94%",
      "--text-secondary": "0 0% 70%",
      "--text-muted": "0 0% 52%",
      "--text-on-primary": "0 0% 10%",
      "--chart-1": "239 76% 72%",
      "--chart-2": "279 60% 68%",
      "--chart-3": "199 62% 68%",
      "--chart-4": "319 58% 68%",
      "--chart-5": "159 54% 66%",
      "--chart-neutral": "0 0% 50%",
    },
  };
}

/**
 * Generate a complete theme palette from a seed hex color.
 * Derives all CSS variable values for light and dark modes.
 */
export function generateThemePalette(seedHex: string): ThemePalette {
  const { h, s } = hexToHSL(seedHex);
  const softSurfaceS = Math.max(Math.min(s - 18, 52), 28);
  const softBorderS = Math.max(Math.min(s - 28, 36), 18);
  const textS = Math.max(Math.min(s - 42, 22), 10);

  return {
    light: {
      "--primary": `${h} ${s}% 50%`,
      "--primary-hover": `${h} ${s}% 43%`,
      "--primary-active": `${h} ${s}% 37%`,
      // 浅色主题不再把背景压到接近纯白，确保主题色能在页面底色上肉眼可见。
      "--primary-subtle": `${h} ${Math.max(s - 14, 24)}% 90%`,
      "--background": `${h} ${softSurfaceS}% 94%`,
      "--surface": `${h} ${Math.max(softSurfaceS - 6, 22)}% 97%`,
      "--surface-hover": `${h} ${Math.max(softSurfaceS - 2, 24)}% 92%`,
      "--border": `${h} ${softBorderS}% 80%`,
      "--border-subtle": `${h} ${Math.max(softBorderS - 4, 14)}% 87%`,
      "--text": `${h} ${textS}% 14%`,
      "--text-secondary": `${h} ${Math.max(textS - 4, 8)}% 34%`,
      "--text-muted": `${h} ${Math.max(textS - 6, 6)}% 46%`,
      "--text-on-primary": `0 0% 100%`,
      "--chart-1": `${h} ${s}% 55%`,
      "--chart-2": `${(h + 40) % 360} ${Math.max(s - 10, 15)}% 55%`,
      "--chart-3": `${(h - 40 + 360) % 360} ${Math.max(s - 10, 15)}% 55%`,
      "--chart-4": `${(h + 80) % 360} ${Math.max(s - 15, 15)}% 55%`,
      "--chart-5": `${(h - 80 + 360) % 360} ${Math.max(s - 15, 15)}% 55%`,
      "--chart-neutral": `${h} 10% 60%`,
    },
    dark: {
      "--primary": `${h} ${Math.max(s - 5, 10)}% 60%`,
      "--primary-hover": `${h} ${Math.max(s - 5, 10)}% 67%`,
      "--primary-active": `${h} ${Math.max(s - 5, 10)}% 73%`,
      "--primary-subtle": `${h} ${Math.max(s - 25, 10)}% 15%`,
      "--background": `${h} 20% 7%`,
      "--surface": `${h} 18% 11%`,
      "--surface-hover": `${h} 20% 15%`,
      "--border": `${h} 18% 20%`,
      "--border-subtle": `${h} 15% 15%`,
      "--text": `${h} 10% 93%`,
      "--text-secondary": `${h} 8% 65%`,
      "--text-muted": `${h} 6% 48%`,
      "--text-on-primary": `${h} 15% 10%`,
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
 * Convert a CSS hsl()/hsla() string to hsla() format with alpha.
 * Handles both hsl(H S% L%) space-separated (Tailwind modern format) and hsl(H,S%,L%) comma-separated.
 */
export function hslToHsla(hsl: string, alpha: number): string {
  const HEX_COLOR_RE = /^#[0-9a-fA-F]{6}$/;
  if (HEX_COLOR_RE.test(hsl)) {
    return hsl.replace("#", "").length === 6
      ? `hsla(${parseInt(hsl.slice(1, 3), 16)}, ${parseInt(hsl.slice(3, 5), 16)}, ${parseInt(hsl.slice(5, 7), 16)}, ${alpha})`
      : `hsla(0, 0%, 0%, ${alpha})`;
  }

  let normalized = hsl.trim();

  if (normalized.startsWith("hsl(") || normalized.startsWith("hsla(")) {
    normalized = normalized.replace(/^hsla?\(|\)$/g, "").trim();
  }

  const parts = normalized.split(/\s+/);
  if (parts.length < 3) {
    return `hsla(0, 0%, 50%, ${alpha})`;
  }

  const h = parseFloat(parts[0]);
  const s = parseFloat(parts[1].replace("%", ""));
  const l = parseFloat(parts[2].replace("%", ""));

  if (isNaN(h) || isNaN(s) || isNaN(l)) {
    return `hsla(0, 0%, 50%, ${alpha})`;
  }

  return `hsla(${h}, ${s}%, ${l}%, ${alpha})`;
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
