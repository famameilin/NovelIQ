import { useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { FileQuestion } from "lucide-react";
import { Button } from "@/components/ui/button";

/**
 * 创建时间: 2026-04-04
 * 创建者: GLM-5
 * 任务: 重构 NotFoundPage 组件
 * 说明: 创建美观的 404 页面，包含居中布局、视觉元素、友好文案和进场动画
 *
 * 修改时间: 2026-04-04
 * 修改者: GLM-5
 * 修改内容:
 * - 调整动画时长符合规范（300ms）
 * - 提升可访问性，添加 ARIA 属性
 * - 提取动画配置为常量，避免每次渲染重新创建
 */

const PAGE_VARIANTS = {
  container: {
    initial: { opacity: 0, y: 20 },
    animate: {
      opacity: 1,
      y: 0,
      transition: {
        duration: 0.3,
        ease: "easeOut",
      },
    },
  },
  icon: {
    initial: { opacity: 0, scale: 0.8 },
    animate: {
      opacity: 1,
      scale: 1,
      transition: {
        duration: 0.4,
        delay: 0.1,
        ease: "easeOut",
      },
    },
  },
  text: {
    initial: { opacity: 0, y: 10 },
    animate: {
      opacity: 1,
      y: 0,
      transition: {
        duration: 0.3,
        delay: 0.2,
        ease: "easeOut",
      },
    },
  },
  button: {
    initial: { opacity: 0, y: 10 },
    animate: {
      opacity: 1,
      y: 0,
      transition: {
        duration: 0.3,
        delay: 0.3,
        ease: "easeOut",
      },
    },
  },
} as const;

export function NotFoundPage() {
  const navigate = useNavigate();

  return (
    <motion.div
      className="flex min-h-full w-full items-center justify-center p-8"
      variants={PAGE_VARIANTS.container}
      initial="initial"
      animate="animate"
    >
      <div className="text-center">
        <motion.div
          variants={PAGE_VARIANTS.icon}
          initial="initial"
          animate="animate"
          className="mb-6"
        >
          <div className="relative inline-block">
            <FileQuestion 
              className="h-24 w-24 text-text-muted/40 dark:text-text-muted/30" 
              aria-hidden="true"
            />
            <span 
              className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 text-4xl font-bold text-text-muted/60 dark:text-text-muted/50"
              role="img"
              aria-label="错误代码 404"
            >
              404
            </span>
          </div>
        </motion.div>

        <motion.h1
          variants={PAGE_VARIANTS.text}
          initial="initial"
          animate="animate"
          className="mb-3 text-2xl font-bold text-text"
          role="heading"
          aria-level={1}
        >
          页面走丢了
        </motion.h1>

        <motion.p
          variants={PAGE_VARIANTS.text}
          initial="initial"
          animate="animate"
          className="mb-8 text-base text-text-secondary"
        >
          抱歉，您访问的页面不存在
        </motion.p>

        <motion.div
          variants={PAGE_VARIANTS.button}
          initial="initial"
          animate="animate"
        >
          <Button
            onClick={() => navigate("/")}
            size="lg"
            className="px-8"
            aria-label="返回首页"
          >
            返回首页
          </Button>
        </motion.div>
      </div>
    </motion.div>
  );
}
