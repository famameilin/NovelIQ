import { Moon, Sun, BookOpen } from "lucide-react";
import { Link } from "react-router-dom";
import { useThemeStore } from "@/store/themeStore";
import { cn } from "@/lib/cn";

export function TopBar() {
  const { isDark, toggleDark } = useThemeStore();

  return (
    <header className="sticky top-0 z-50 flex h-14 items-center justify-between border-b border-border bg-surface px-6">
      <Link to="/" className="flex items-center gap-2 text-text hover:opacity-80 transition-opacity">
        <BookOpen className="h-5 w-5 text-primary" />
        <span className="text-lg font-semibold">小说量化分析</span>
      </Link>

      <div className="flex items-center gap-3">
        <button
          onClick={toggleDark}
          className={cn(
            "inline-flex h-9 w-9 items-center justify-center rounded-md",
            "text-text-secondary hover:bg-surface-hover hover:text-text transition-colors"
          )}
          aria-label="切换深浅模式"
        >
          {isDark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
        </button>
      </div>
    </header>
  );
}
