import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { motion } from "framer-motion";
import { cn } from "@/lib/cn";

/* ------------------------------------------------------------------ */
/*  Card 变体                                                          */
/* ------------------------------------------------------------------ */

const cardVariants = cva(
  "border bg-surface",
  {
    variants: {
      variant: {
        default: "border-border shadow-sm",
        elevated:
          "border-border overflow-hidden bg-surface shadow-sm",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
);

export interface CardProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof cardVariants> {}

/* ------------------------------------------------------------------ */
/*  Card 组件                                                          */
/* ------------------------------------------------------------------ */

/**
 * 2026-04-28，任务：分析详情页单屏布局收口
 * 修改原因：elevated 卡片 hover 位移提高到 2px，并缩短过渡时长，让位移和阴影变化更接近同时发生。
 */
const Card = React.forwardRef<HTMLDivElement, CardProps>(
  ({ className, variant, ...props }, ref) => {
    const baseClasses = cardVariants({ variant });

    if (variant === "elevated") {
      return (
        <motion.div
          ref={ref}
          className={cn(baseClasses, className)}
          whileHover={{ y: -2 }}
          transition={{ duration: 0.2, ease: "easeOut" }}
          {...(props as React.ComponentProps<typeof motion.div>)}
        />
      );
    }

    return (
      <div
        ref={ref}
        className={cn(baseClasses, className)}
        {...props}
      />
    );
  }
);
Card.displayName = "Card";

/* ------------------------------------------------------------------ */
/*  子组件（保持不变）                                                 */
/* ------------------------------------------------------------------ */

const CardHeader = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement>
>(({ className, ...props }, ref) => (
  <div
    ref={ref}
    className={cn("flex flex-col space-y-1.5 p-6", className)}
    {...props}
  />
));
CardHeader.displayName = "CardHeader";

const CardTitle = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement>
>(({ className, ...props }, ref) => (
  <div
    ref={ref}
    className={cn("font-semibold leading-none tracking-tight text-text", className)}
    {...props}
  />
));
CardTitle.displayName = "CardTitle";

const CardDescription = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement>
>(({ className, ...props }, ref) => (
  <div
    ref={ref}
    className={cn("text-sm text-text-muted", className)}
    {...props}
  />
));
CardDescription.displayName = "CardDescription";

const CardContent = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement>
>(({ className, ...props }, ref) => (
  <div ref={ref} className={cn("p-6 pt-0", className)} {...props} />
));
CardContent.displayName = "CardContent";

const CardFooter = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement>
>(({ className, ...props }, ref) => (
  <div
    ref={ref}
    className={cn("flex items-center p-6 pt-0", className)}
    {...props}
  />
));
CardFooter.displayName = "CardFooter";

// eslint-disable-next-line react-refresh/only-export-components -- variants and sub-components
export { Card, cardVariants, CardHeader, CardFooter, CardTitle, CardDescription, CardContent };
