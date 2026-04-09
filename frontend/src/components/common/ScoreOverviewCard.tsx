import { useRef, useId } from "react";
import { motion, useInView } from "framer-motion";
import { useNavigate } from "react-router-dom";
import { ArrowRight } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";

export interface ScoreOverviewCardProps {
  foreshadowRate?: number | null;
  powerStance?: number | null;
  civilianDignity?: number | null;
  culturalDepth?: number | null;
  novelId: string;
  className?: string;
}

function MiniProgressRing({
  progress,
  size = 48,
  strokeWidth = 4,
}: {
  progress: number;
  size?: number;
  strokeWidth?: number;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const isInView = useInView(ref, { once: true, margin: "-20px" });

  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const clampedProgress = Math.max(0, Math.min(100, progress));
  const gradientId = `score-ring-${useId()}`;

  return (
    <div
      ref={ref}
      className="relative inline-flex items-center justify-center"
      style={{ width: size, height: size }}
      role="progressbar"
      aria-valuenow={Math.round(clampedProgress)}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label={`伏笔兑现率 ${Math.round(clampedProgress)}%`}
    >
      <svg
        width={size}
        height={size}
        className="-rotate-90"
        viewBox={`0 0 ${size} ${size}`}
        aria-hidden="true"
      >
        <defs>
          <linearGradient id={gradientId} gradientUnits="userSpaceOnUse">
            <stop offset="0%" stopColor="hsl(var(--primary))" />
            <stop offset="100%" stopColor="hsl(var(--primary-hover))" />
          </linearGradient>
        </defs>
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          strokeWidth={strokeWidth}
          className="stroke-border"
        />
        <motion.circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          strokeWidth={strokeWidth}
          strokeLinecap="round"
          stroke={`url(#${gradientId})`}
          initial={{ strokeDashoffset: circumference }}
          animate={
            isInView
              ? { strokeDashoffset: circumference - (clampedProgress / 100) * circumference }
              : { strokeDashoffset: circumference }
          }
          transition={{ duration: 0.8, ease: "easeOut" }}
          style={{ strokeDasharray: circumference }}
        />
      </svg>
      <span className="absolute text-xs font-semibold tabular-nums text-text">
        {Math.round(clampedProgress)}%
      </span>
    </div>
  );
}

function DotRating({
  score,
  maxScore = 5,
}: {
  score: number;
  maxScore?: number;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const isInView = useInView(ref, { once: true, margin: "-20px" });

  return (
    <div ref={ref} className="flex items-center gap-1" role="img" aria-label={`评分 ${score}/${maxScore}`}>
      {Array.from({ length: maxScore }).map((_, i) => (
        <motion.svg
          key={i}
          width={8}
          height={8}
          viewBox="0 0 8 8"
          initial={{ opacity: 0, scale: 0.5 }}
          animate={isInView ? { opacity: 1, scale: 1 } : { opacity: 0, scale: 0.5 }}
          transition={{ duration: 0.3, delay: i * 0.05 }}
          aria-hidden="true"
        >
          <circle
            cx={4}
            cy={4}
            r={3.5}
            className={i < score ? "fill-primary" : "fill-border"}
          />
        </motion.svg>
      ))}
    </div>
  );
}

function ScoreRow({
  label,
  score,
  maxScore = 5,
}: {
  label: string;
  score?: number | null;
  maxScore?: number;
}) {
  if (score == null) {
    return (
      <div className="flex items-center justify-between">
        <span className="text-xs text-text-muted">{label}</span>
        <span className="text-xs text-text-muted">暂无数据</span>
      </div>
    );
  }

  const clampedScore = Math.max(0, Math.min(maxScore, score));

  return (
    <div className="flex items-center justify-between">
      <span className="text-xs text-text-muted">{label}</span>
      <div className="flex items-center gap-2">
        <DotRating score={clampedScore} maxScore={maxScore} />
        <span className="text-xs font-medium tabular-nums text-text">
          {clampedScore}/{maxScore}
        </span>
      </div>
    </div>
  );
}

export function ScoreOverviewCard({
  foreshadowRate,
  powerStance,
  civilianDignity,
  culturalDepth,
  novelId,
  className,
}: ScoreOverviewCardProps) {
  const navigate = useNavigate();

  const foreshadowPct =
    foreshadowRate != null ? Math.round(foreshadowRate * 100) : null;

  return (
    <Card variant="elevated" className={cn("rounded-xl", className)}>
      <CardContent className="flex flex-col gap-4 p-5">
        <h3 className="text-xl font-semibold text-text">评分速览</h3>

        <div className="flex items-center gap-3">
          {foreshadowPct != null ? (
            <>
              <MiniProgressRing progress={foreshadowPct} />
              <div>
                <p className="text-xs text-text-muted">伏笔兑现率</p>
                <p className="text-sm font-medium text-text">{foreshadowPct}%</p>
              </div>
            </>
          ) : (
            <div className="flex items-center gap-3">
              <div className="flex h-12 w-12 items-center justify-center rounded-full bg-surface-hover">
                <span className="text-xs text-text-muted">—</span>
              </div>
              <div>
                <p className="text-xs text-text-muted">伏笔兑现率</p>
                <p className="text-sm text-text-muted">暂无数据</p>
              </div>
            </div>
          )}
        </div>

        <div className="flex flex-col gap-2">
          <ScoreRow label="权力立场" score={powerStance} />
          <ScoreRow label="平民尊严" score={civilianDignity} />
          <ScoreRow label="文化深度" score={culturalDepth} />
        </div>

        <div className="mt-auto pt-2">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => navigate(`/novels/${novelId}/diagnosis`)}
            className="group flex items-center gap-1 text-xs text-text-muted transition-colors hover:text-primary"
          >
            查看完整诊断报告
            <ArrowRight className="h-3 w-3 transition-transform group-hover:translate-x-0.5" />
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
