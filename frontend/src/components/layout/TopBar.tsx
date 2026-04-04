/**
 * 创建时间：2026-04-04
 * 创建者：GLM-5
 * 任务：创建 TopBar 组件
 * 说明：顶部导航栏组件，包含 Logo、面包屑导航和深浅模式切换
 *
 * 修改时间：2026-04-04
 * 修改者：GLM-5
 * 修改内容：添加面包屑导航和小说名显示功能
 */
import { Moon, Sun, BookOpen } from "lucide-react";
import { Link, useParams, useLocation } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useThemeStore } from "@/store/themeStore";
import { cn } from "@/lib/cn";
import { Breadcrumb, getBreadcrumbLabel } from "./Breadcrumb";
import { getNovel } from "@/api/novels";

export function TopBar() {
  const { isDark, toggleDark } = useThemeStore();
  const { novelId } = useParams<{ novelId: string }>();
  const location = useLocation();

  const isHomePage = location.pathname === "/";

  const { data: novel, isLoading, isError } = useQuery({
    queryKey: ["novel", novelId],
    queryFn: () => getNovel(novelId!),
    enabled: !!novelId,
  });

  const breadcrumbItems = [];
  breadcrumbItems.push({ label: "首页", href: "/" });

  if (novelId && !isHomePage) {
    if (isLoading) {
      breadcrumbItems.push({ label: "加载中..." });
    } else if (isError || !novel) {
      breadcrumbItems.push({ label: "未知小说" });
    } else {
      const basePath = `/novels/${novelId}`;
      const currentPath = location.pathname.replace(basePath, "");

      breadcrumbItems.push({
        label: novel.title,
        href: basePath,
      });

      if (currentPath && currentPath !== "") {
        breadcrumbItems.push({
          label: getBreadcrumbLabel(currentPath),
        });
      }
    }
  }

  const showBreadcrumb = !isHomePage && novelId;

  return (
    <header className="sticky top-0 z-50 flex h-14 items-center justify-between border-b border-border bg-surface px-6">
      <Link to="/" className="flex items-center gap-2 text-text hover:opacity-80 transition-opacity">
        <BookOpen className="h-5 w-5 text-primary" />
        <span className="text-lg font-semibold">小说量化分析</span>
      </Link>

      {showBreadcrumb && (
        <div className="flex-1 flex justify-center">
          <Breadcrumb items={breadcrumbItems} />
        </div>
      )}

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
