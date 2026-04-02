import { Toaster as SonnerToaster } from "sonner";
import { useThemeStore } from "@/store/themeStore";

export function Toaster() {
  const isDark = useThemeStore((s) => s.isDark);

  return (
    <SonnerToaster
      theme={isDark ? "dark" : "light"}
      position="top-right"
      richColors
      toastOptions={{
        style: {
          background: "hsl(var(--surface))",
          color: "hsl(var(--text))",
          border: "1px solid hsl(var(--border))",
        },
      }}
    />
  );
}
