import { motion } from "framer-motion";
import { NovelCard, type NovelCardData } from "@/components/common/NovelCard";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { BookOpen, Plus, Upload } from "lucide-react";
import { cn } from "@/lib/cn";

/* ------------------------------------------------------------------ */
/*  Types                                                             */
/* ------------------------------------------------------------------ */

export interface NovelGridProps {
  novels: NovelCardData[];
  isLoading?: boolean;
  onView?: (id: string) => void;
  onDelete?: (id: string) => void;
  onUpload?: () => void;
  className?: string;
}

/* ------------------------------------------------------------------ */
/*  Animation Variants                                                */
/* ------------------------------------------------------------------ */

const containerVariants = {
  hidden: { opacity: 0 },
  visible: {
    opacity: 1,
    transition: {
      staggerChildren: 0.08,
      delayChildren: 0.1,
    },
  },
};

const itemVariants = {
  hidden: { opacity: 0, y: 20 },
  visible: {
    opacity: 1,
    y: 0,
    transition: {
      duration: 0.4,
      ease: [0.16, 1, 0.3, 1],
    },
  },
};

/* ------------------------------------------------------------------ */
/*  Skeleton Card                                                     */
/* ------------------------------------------------------------------ */

function SkeletonCard() {
  return (
    <Card className="overflow-hidden border-border">
      {/* 封面占位 */}
      <div className="aspect-[3/4] animate-pulse bg-surface-hover" />

      {/* 内容占位 */}
      <div className="space-y-3 p-4">
        <div className="h-5 w-3/4 animate-pulse rounded bg-surface-hover" />
        <div className="h-4 w-1/2 animate-pulse rounded bg-surface-hover" />
        <div className="flex items-center justify-between pt-2">
          <div className="h-6 w-16 animate-pulse rounded-full bg-surface-hover" />
          <div className="h-4 w-20 animate-pulse rounded bg-surface-hover" />
        </div>
      </div>
    </Card>
  );
}

/* ------------------------------------------------------------------ */
/*  Empty State                                                       */
/* ------------------------------------------------------------------ */

function EmptyState({ onUpload }: { onUpload?: () => void }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5 }}
      className="flex flex-col items-center justify-center py-20"
    >
      <div className="mb-6 flex h-24 w-24 items-center justify-center rounded-full bg-primary-subtle">
        <BookOpen className="h-12 w-12 text-primary" />
      </div>

      <h3 className="mb-2 text-xl font-semibold text-text">
        还没有小说
      </h3>

      <p className="mb-8 max-w-md text-center text-text-secondary">
        上传一本中文网络小说，开始探索它的叙事结构、情感走向和人物关系。
      </p>

      {onUpload && (
        <Button size="lg" onClick={onUpload} className="gap-2">
          <Upload className="h-5 w-5" />
          上传小说
        </Button>
      )}
    </motion.div>
  );
}

/* ------------------------------------------------------------------ */
/*  Main Component                                                    */
/* ------------------------------------------------------------------ */

export function NovelGrid({
  novels,
  isLoading = false,
  onView,
  onDelete,
  onUpload,
  className,
}: NovelGridProps) {
  // 加载状态：显示骨架屏
  if (isLoading) {
    return (
      <div
        className={cn(
          "grid gap-6 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4",
          className
        )}
      >
        {Array.from({ length: 8 }).map((_, i) => (
          <SkeletonCard key={i} />
        ))}
      </div>
    );
  }

  // 空状态
  if (novels.length === 0) {
    return <EmptyState onUpload={onUpload} />;
  }

  // 正常列表
  return (
    <motion.div
      variants={containerVariants}
      initial="hidden"
      animate="visible"
      className={cn(
        "grid gap-6 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4",
        className
      )}
    >
      {novels.map((novel) => (
        <motion.div key={novel.id} variants={itemVariants}>
          <NovelCard
            novel={novel}
            onView={onView}
            onDelete={onDelete}
          />
        </motion.div>
      ))}
    </motion.div>
  );
}

export default NovelGrid;
