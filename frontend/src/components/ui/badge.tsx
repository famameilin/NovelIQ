import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/cn";

const badgeVariants = cva(
  "inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold focus:outline-none focus:ring-2 focus:ring-primary/50",
  {
    variants: {
      variant: {
        default:
          "border-transparent bg-primary/90 text-text-on-primary hover:bg-primary",
        secondary:
          "border-transparent bg-primary-subtle text-primary hover:bg-primary-subtle/80",
        outline: "border-border text-text-secondary hover:bg-surface-hover",
        destructive:
          "border-transparent bg-[hsl(var(--chart-negative))] text-white hover:bg-[hsl(var(--chart-negative))]/90",
        success:
          "border-transparent bg-[hsl(var(--chart-positive))] text-white hover:bg-[hsl(var(--chart-positive))]/90",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return (
    <div
      className={cn(badgeVariants({ variant }), className)}
      {...props}
    />
  );
}

export { Badge, badgeVariants };
