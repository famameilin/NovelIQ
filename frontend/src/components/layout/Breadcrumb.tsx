/**
 * 实现面包屑导航组件，支持可点击/不可点击状态，使用 ChevronRight 图标作为分隔符
 */
import { ChevronRight } from "lucide-react";
import { Link } from "react-router-dom";
import { cn } from "@/lib/cn";

interface BreadcrumbItem {
  id: string;
  label: string;
  href?: string;
}

interface BreadcrumbProps {
  items: BreadcrumbItem[];
}

export function Breadcrumb({ items }: BreadcrumbProps) {
  return (
    <nav className="flex items-center" aria-label="面包屑导航">
      {items.map((item, index) => {
        const isLast = index === items.length - 1;
        const isClickable = !!item.href && !isLast;

        return (
          <div key={item.id} className="flex items-center">
            {index > 0 && (
              <ChevronRight className="h-4 w-4 text-text-muted mx-2" />
            )}
            {isClickable ? (
              <Link
                to={item.href!}
                className={cn(
                  "text-text-secondary hover:text-text transition-colors cursor-pointer"
                )}
              >
                {item.label}
              </Link>
            ) : (
              <span
                className={cn(
                  isLast
                    ? "text-text font-medium"
                    : "text-text-secondary"
                )}
              >
                {item.label}
              </span>
            )}
          </div>
        );
      })}
    </nav>
  );
}

export const routeNameMap: Record<string, string> = {
  "": "仪表盘",
  "/curves": "情绪/节奏曲线",
  "/characters": "角色分析",
  "/graph": "人物关系图谱",
  "/topics": "主题分布",
  "/timeline": "叙事时间轴",
  "/diagnosis": "诊断报告",
};

export function getBreadcrumbLabel(path: string): string {
  return routeNameMap[path] || path;
}
