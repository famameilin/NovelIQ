/**
 * 顶部导航栏组件，包含 Logo、面包屑导航和深浅模式切换
 *
 * - 新增面包屑导航功能，支持多级路由显示
 * - 新增小说名称显示，通过 API 获取当前小说信息
 * - 新增加载状态和错误状态处理
 * - 优化数据获取配置，添加缓存和错误重试
 * - 优化面包屑布局，改为左对齐
 */
import { Moon, Sun } from "lucide-react";
import { Link, useParams, useLocation } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useThemeStore } from "@/store/themeStore";
import { useNovelStore } from "@/store/novelStore";
import { cn } from "@/lib/cn";
import { Breadcrumb, getBreadcrumbLabel } from "./Breadcrumb";
import { getNovel } from "@/api/novels";

const TOPBAR_LOGO_SRC = "/novel%20qa%20icon.svg";

/**
 * 2026-05-01: 为“顶部导航改用用户提供 logo”任务更新 TopBar。
 * 原因：保持顶部文案不变，仅将通用书本图标替换为品牌 SVG，统一前端品牌符号。
 */
export function TopBar() {
  const { isDark, toggleDark } = useThemeStore();
  const { novelId } = useParams<{ novelId: string }>();
  const location = useLocation();
  const currentTaskId = useNovelStore((s) => s.currentTaskId);
  const cachedNovel = useNovelStore((s) => 
    novelId ? s.getNovelById(novelId) : undefined
  );

  const isHomePage = location.pathname === "/";

  // 优先从 store 缓存读取，仅在缓存未命中时请求 API
  const {
    data: apiNovel,
    isLoading,
    isError,
  } = useQuery({
    queryKey: ["novel", novelId],
    queryFn: () => getNovel(novelId!),
    enabled: !!novelId && !cachedNovel, // 缓存命中时跳过 API 请求
    staleTime: 5 * 60 * 1000,
    gcTime: 10 * 60 * 1000,
    retry: 2,
    refetchOnWindowFocus: false,
  });

  // 缓存优先，API 结果作为 fallback
  const novel = cachedNovel ?? apiNovel;

  const breadcrumbItems = [];
  breadcrumbItems.push({ id: "home", label: "首页", href: "/" });

  if (novelId && !isHomePage) {
    const taskQuery = currentTaskId ? `?task_id=${currentTaskId}` : "";
    
    if (isLoading) {
      breadcrumbItems.push({ id: "loading", label: "加载中..." });
    } else if (isError || !novel) {
      breadcrumbItems.push({ id: "error", label: "未知小说" });
    } else {
      const basePath = `/novels/${novelId}`;
      const currentPath = location.pathname.replace(basePath, "");

      breadcrumbItems.push({
        id: `novel-${novelId}`,
        label: novel.title,
        href: `${basePath}${taskQuery}`,
      });

      if (currentPath && currentPath !== "") {
        breadcrumbItems.push({
          id: `page-${currentPath}`,
          label: getBreadcrumbLabel(currentPath),
        });
      }
    }
  }

  const showBreadcrumb = !isHomePage && novelId;

  return (
    <header className="sticky top-0 z-50 flex h-14 items-center justify-between border-b border-border bg-surface px-6">
      <Link to="/" className="flex items-center gap-2 text-text hover:opacity-80 transition-opacity">
        <span className="flex h-6 w-6 items-center justify-center rounded-md">
          <img
            src={TOPBAR_LOGO_SRC}
            alt="NovelIQ logo"
            className="h-full w-full object-contain"
            loading="eager"
            decoding="async"
          />
        </span>
        <span className="text-lg font-semibold">小说量化分析</span>
      </Link>

      {showBreadcrumb && (
        <div className="flex-1 flex justify-start px-8">
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
