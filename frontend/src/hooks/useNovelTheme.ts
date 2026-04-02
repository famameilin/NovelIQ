import { useEffect } from "react";
import { useThemeStore } from "@/store/themeStore";
import { generateThemePalette } from "@/lib/theme";

/**
 * Applies the dynamic theme palette to :root CSS variables.
 * Reacts to seedColor and isDark changes from the theme store.
 */
export function useNovelTheme() {
  const { seedColor, isDark } = useThemeStore();

  useEffect(() => {
    const palette = generateThemePalette(seedColor);
    const vars = isDark ? palette.dark : palette.light;
    const root = document.documentElement;

    Object.entries(vars).forEach(([key, value]) => {
      root.style.setProperty(key, value);
    });

    root.classList.toggle("dark", isDark);
  }, [seedColor, isDark]);
}
