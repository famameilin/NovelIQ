import { Upload, BookOpen, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";

/* ------------------------------------------------------------------ */
/*  类型定义                                                           */
/* ------------------------------------------------------------------ */

export interface HeroSectionProps {
  onUpload?: () => void;
  novelCount?: number;
  className?: string;
}

/* ------------------------------------------------------------------ */
/*  组件主体                                                           */
/* ------------------------------------------------------------------ */

export function HeroSection({
  onUpload,
  novelCount,
  className,
}: HeroSectionProps) {
  return (
    <section
      className={cn(
        "relative flex flex-col justify-center overflow-hidden",
        className
      )}
    >
      {/* 动态背景 */}
      <div className="absolute inset-0 overflow-hidden">
        {/* 渐变底色 */}
        <div className="absolute inset-0 bg-gradient-to-br from-primary/5 via-transparent to-chart-2/5" />

        {/* 浮动装饰圆 */}
        <div className="absolute -right-20 top-1/4 h-80 w-80 rounded-full bg-primary/10 blur-3xl animate-pulse" style={{ animationDuration: '8s' }} />
        <div className="absolute -left-10 bottom-1/4 h-60 w-60 rounded-full bg-chart-2/10 blur-3xl animate-pulse" style={{ animationDuration: '10s' }} />

        {/* 网格纹理 */}
        <div
          className="absolute inset-0 opacity-[0.02]"
          style={{
            backgroundImage: `linear-gradient(to right, hsl(var(--primary)) 1px, transparent 1px),
                              linear-gradient(to bottom, hsl(var(--primary)) 1px, transparent 1px)`,
            backgroundSize: '60px 60px'
          }}
        />
      </div>

      {/* 主内容区 */}
      <div className="relative z-10 flex h-full items-center px-6">
        <div className="mx-auto flex w-full max-w-5xl items-center justify-between">
          {/* 左侧标题 */}
          <div className="flex items-center gap-4">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary/10">
              <Sparkles className="h-5 w-5 text-primary" />
            </div>
            <div>
              <h1 className="text-xl font-bold text-gray-900 dark:text-gray-100">
                探索小说的
                <span className="ml-1 bg-gradient-to-r from-primary to-chart-2 bg-clip-text text-transparent">
                  叙事奥秘
                </span>
              </h1>
              {novelCount !== undefined && novelCount > 0 && (
                <p className="text-xs text-gray-600 dark:text-gray-400">
                  <BookOpen className="mr-1 inline h-3 w-3" />
                  已上传 {novelCount} 本小说
                </p>
              )}
            </div>
          </div>

          {/* 右侧分页 */}
          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" onClick={onUpload} className="gap-2">
              <Upload className="h-4 w-4" />
              上传
            </Button>
          </div>
        </div>
      </div>

    </section>
  );
}

export default HeroSection;
