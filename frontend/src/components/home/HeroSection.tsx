import { motion } from "framer-motion";
import { Upload, BookOpen, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";

/* ------------------------------------------------------------------ */
/*  Types                                                             */
/* ------------------------------------------------------------------ */

export interface HeroSectionProps {
  onUpload?: () => void;
  novelCount?: number;
  className?: string;
}

/* ------------------------------------------------------------------ */
/*  Component                                                         */
/* ------------------------------------------------------------------ */

export function HeroSection({
  onUpload,
  novelCount,
  className,
}: HeroSectionProps) {
  return (
    <section
      className={cn(
        "relative overflow-hidden rounded-2xl bg-gradient-to-br from-primary/10 via-primary/5 to-transparent px-6 py-12 sm:px-12 sm:py-16 lg:px-16",
        className
      )}
    >
      {/* 装饰性背景元素 */}
      <div className="absolute -right-20 -top-20 h-64 w-64 rounded-full bg-primary/5 blur-3xl" />
      <div className="absolute -bottom-10 -left-10 h-40 w-40 rounded-full bg-chart-2/10 blur-2xl" />

      <div className="relative z-10 mx-auto max-w-4xl text-center">
        {/* 徽章 */}
        <motion.div
          initial={{ opacity: 0, y: -10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5 }}
          className="mb-6 inline-flex items-center gap-2 rounded-full bg-primary/10 px-4 py-1.5"
        >
          <Sparkles className="h-4 w-4 text-primary" />
          <span className="text-sm font-medium text-primary">
            AI 驱动的网文分析
          </span>
        </motion.div>

        {/* 标题 */}
        <motion.h1
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, delay: 0.1 }}
          className="mb-4 text-3xl font-bold tracking-tight text-text sm:text-4xl lg:text-5xl"
        >
          探索小说的
          <span className="bg-gradient-to-r from-primary to-chart-2 bg-clip-text text-transparent">
            叙事奥秘
          </span>
        </motion.h1>

        {/* 副标题 */}
        <motion.p
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, delay: 0.2 }}
          className="mx-auto mb-8 max-w-2xl text-base text-text-secondary sm:text-lg"
        >
          上传中文网络小说，AI 将自动分析其叙事结构、情感走向、人物关系和文化元素，
          帮助你更深入地理解作品。
        </motion.p>

        {/* 统计信息 */}
        {novelCount !== undefined && novelCount > 0 && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.5, delay: 0.3 }}
            className="mb-8 flex items-center justify-center gap-6 text-sm text-text-muted"
          >
            <div className="flex items-center gap-2">
              <BookOpen className="h-4 w-4" />
              <span>已上传 {novelCount} 本小说</span>
            </div>
          </motion.div>
        )}

        {/* CTA 按钮 */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, delay: 0.3 }}
          className="flex flex-col items-center justify-center gap-4 sm:flex-row"
        >
          <Button
            size="lg"
            onClick={onUpload}
            className="group gap-2 px-8"
          >
            <Upload className="h-5 w-5 transition-transform group-hover:-translate-y-0.5" />
            上传小说
          </Button>

          <Button
            variant="outline"
            size="lg"
            onClick={() => {
              // Scroll to novels grid
              document
                .getElementById("novels-grid")
                ?.scrollIntoView({ behavior: "smooth" });
            }}
            className="gap-2"
          >
            <BookOpen className="h-5 w-5" />
            浏览已有小说
          </Button>
        </motion.div>
      </div>
    </section>
  );
}

export default HeroSection;
