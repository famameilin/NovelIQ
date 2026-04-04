import { NavLink, useParams } from "react-router-dom";
import {
  LayoutDashboard,
  TrendingUp,
  Users,
  Network,
  MessageSquare,
  Clock,
  FileText,
  PanelLeftClose,
  PanelLeft,
} from "lucide-react";
import { useState } from "react";
import { cn } from "@/lib/cn";
import { useNovelStore } from "@/store/novelStore";

const navItems = [
  { to: "", icon: LayoutDashboard, label: "仪表盘" },
  { to: "/curves", icon: TrendingUp, label: "情绪/节奏曲线" },
  { to: "/characters", icon: Users, label: "角色分析" },
  { to: "/graph", icon: Network, label: "人物关系图谱" },
  { to: "/topics", icon: MessageSquare, label: "主题分布" },
  { to: "/timeline", icon: Clock, label: "叙事时间轴" },
  { to: "/diagnosis", icon: FileText, label: "诊断报告" },
];

export function SideNav() {
  const { novelId } = useParams<{ novelId: string }>();
  const currentTaskId = useNovelStore((s) => s.currentTaskId);
  const [collapsed, setCollapsed] = useState(false);

  if (!novelId) return null;

  const basePath = `/novels/${novelId}`;
  const taskQuery = currentTaskId ? `?task_id=${currentTaskId}` : "";

  return (
    <aside
      className={cn(
        "flex flex-col border-r border-border bg-surface transition-[width] duration-200",
        collapsed ? "w-16" : "w-60"
      )}
    >
      <div className="flex h-10 items-center justify-end px-3">
        <button
          onClick={() => setCollapsed(!collapsed)}
          className="inline-flex h-8 w-8 items-center justify-center rounded-md text-text-muted hover:bg-surface-hover hover:text-text transition-colors"
          aria-label={collapsed ? "展开侧栏" : "收起侧栏"}
        >
          {collapsed ? (
            <PanelLeft className="h-4 w-4" />
          ) : (
            <PanelLeftClose className="h-4 w-4" />
          )}
        </button>
      </div>

      <nav className="flex-1 space-y-1 px-2">
        {navItems.map((item) => (
          <NavLink
            key={item.to}
            to={`${basePath}${item.to}${taskQuery}`}
            end={item.to === ""}
            className={({ isActive }) =>
              cn(
                "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                isActive
                  ? "bg-primary-subtle text-primary"
                  : "text-text-secondary hover:bg-surface-hover hover:text-text"
              )
            }
          >
            <item.icon className="h-4 w-4 shrink-0" />
            {!collapsed && <span>{item.label}</span>}
          </NavLink>
        ))}
      </nav>
    </aside>
  );
}
