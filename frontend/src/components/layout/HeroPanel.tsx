import { BookOpen, Upload, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { HeroPanelProps } from "./types";

export function HeroPanel({
  total,
  isLoading,
  onUpload,
  page,
  totalPages,
  onPageChange,
}: HeroPanelProps) {
  return (
    <aside className="relative flex w-96 shrink-0 flex-col border-r border-border/50 overflow-hidden">
      <div className="absolute inset-0 bg-gradient-to-br from-primary/10 via-surface to-chart-2/5" />
      <div className="absolute -right-20 -top-20 h-64 w-64 rounded-full bg-primary/10 blur-3xl" />
      <div className="absolute -bottom-10 left-10 h-48 w-48 rounded-full bg-chart-2/10 blur-2xl" />

      <div className="relative z-10 flex flex-1 flex-col p-8">
        <div className="mb-8 flex items-center gap-3">
          <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-primary text-text-on-primary shadow-lg shadow-primary/20">
            <BookOpen className="h-6 w-6" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-text">小说分析</h1>
            <p className="text-xs text-text-muted">AI 驱动的网文分析</p>
          </div>
        </div>

        <div className="mb-8">
          <div className="mb-4 inline-flex items-center gap-2 rounded-full bg-primary/10 px-3 py-1.5 border border-primary/20">
            <Sparkles className="h-4 w-4 text-primary" />
            <span className="text-sm font-medium text-primary">探索叙事的奥秘</span>
          </div>
          <h2 className="text-3xl font-bold leading-tight text-text">
            上传中文网络小说，
            <br />
            <span className="bg-gradient-to-r from-primary to-chart-2 bg-clip-text text-transparent">
              开启 AI 分析之旅
            </span>
          </h2>
          <p className="mt-3 text-sm text-text-secondary leading-relaxed">
            自动分析叙事结构、情感走向、人物关系和文化元素，帮助你更深入地理解作品。
          </p>
        </div>

        <div className="mb-6 rounded-xl bg-surface/50 backdrop-blur-sm p-4 border border-border/50">
          <div className="flex items-center gap-2 text-sm text-text-muted mb-1">
            <BookOpen className="h-4 w-4" />
            <span>已上传小说</span>
          </div>
          <p className="text-4xl font-bold text-text">{isLoading ? "..." : total}</p>
        </div>

        <Button
          onClick={onUpload}
          size="lg"
          className="w-full gap-2 shadow-lg shadow-primary/20"
        >
          <Upload className="h-5 w-5" />
          上传小说
        </Button>

        {totalPages && totalPages > 1 && onPageChange && (
          <div className="mt-auto pt-6">
            <div className="flex items-center justify-between">
              <Button
                variant="outline"
                size="sm"
                disabled={(page ?? 1) <= 1}
                onClick={() => onPageChange((page ?? 1) - 1)}
              >
                上一页
              </Button>
              <span className="text-sm text-text-muted">
                {page} / {totalPages}
              </span>
              <Button
                variant="outline"
                size="sm"
                disabled={(page ?? 1) >= totalPages}
                onClick={() => onPageChange((page ?? 1) + 1)}
              >
                下一页
              </Button>
            </div>
          </div>
        )}
      </div>
    </aside>
  );
}
