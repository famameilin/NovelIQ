import { useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { FileQuestion } from "lucide-react";
import { Button } from "@/components/ui/button";

/**
 * 创建时间: 2026-04-04
 * 创建者: GLM-5
 * 任务: 重构 NotFoundPage 组件
 * 说明: 创建美观的 404 页面，包含居中布局、视觉元素、友好文案和进场动画
 */

export function NotFoundPage() {
  const navigate = useNavigate();

  const containerVariants = {
    initial: { opacity: 0, y: 20 },
    animate: {
      opacity: 1,
      y: 0,
      transition: {
        duration: 0.5,
        ease: "easeOut",
      },
    },
  };

  const iconVariants = {
    initial: { opacity: 0, scale: 0.8 },
    animate: {
      opacity: 1,
      scale: 1,
      transition: {
        duration: 0.6,
        delay: 0.1,
        ease: "easeOut",
      },
    },
  };

  const textVariants = {
    initial: { opacity: 0, y: 10 },
    animate: {
      opacity: 1,
      y: 0,
      transition: {
        duration: 0.4,
        delay: 0.2,
        ease: "easeOut",
      },
    },
  };

  const buttonVariants = {
    initial: { opacity: 0, y: 10 },
    animate: {
      opacity: 1,
      y: 0,
      transition: {
        duration: 0.4,
        delay: 0.3,
        ease: "easeOut",
      },
    },
  };

  return (
    <motion.div
      className="flex min-h-full w-full items-center justify-center p-8"
      variants={containerVariants}
      initial="initial"
      animate="animate"
    >
      <div className="text-center">
        <motion.div
          variants={iconVariants}
          initial="initial"
          animate="animate"
          className="mb-6"
        >
          <div className="relative inline-block">
            <FileQuestion className="h-24 w-24 text-text-muted/40 dark:text-text-muted/30" />
            <span className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 text-4xl font-bold text-text-muted/60 dark:text-text-muted/50">
              404
            </span>
          </div>
        </motion.div>

        <motion.h1
          variants={textVariants}
          initial="initial"
          animate="animate"
          className="mb-3 text-2xl font-bold text-text"
        >
          页面走丢了
        </motion.h1>

        <motion.p
          variants={textVariants}
          initial="initial"
          animate="animate"
          className="mb-8 text-base text-text-secondary"
        >
          抱歉，您访问的页面不存在
        </motion.p>

        <motion.div
          variants={buttonVariants}
          initial="initial"
          animate="animate"
        >
          <Button
            onClick={() => navigate("/")}
            size="lg"
            className="px-8"
          >
            返回首页
          </Button>
        </motion.div>
      </div>
    </motion.div>
  );
}
