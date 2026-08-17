import { useRef, useId } from "react";
import { motion, useInView } from "framer-motion";
import { useNavigate } from "react-router-dom";
import { ArrowRight, BarChart3 } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DashboardCardShell,
  getMetricAccentColor,
  getMetricAccentHoverTextClass,
  type MetricAccent,
} from "@/components/common/DashboardCardShell";
import { formatSampleInsufficient } from "@/lib/metricFormat";
import { cn } from "@/lib/cn";

export interface ScoreOverviewCardProps {
  foreshadowExpectation?: number | null;
  powerStance?: number | null;
  civilianDignity?: number | null;
  culturalDepth?: number | null;
  novelId: string;
  className?: string;
}

/**
 * 2026-04-21，任务：仪表盘组件视觉重构
 * 修改原因：让评分速览的环形进度随共享 accent 系统切换，而不是固定只吃 primary
 */
function MiniProgressRing({
  progress,
  accent,
  size = 48,
  strokeWidth = 4,
}: {
  progress: number;
  accent: MetricAccent;
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
      aria-label={`伏笔回收预期 ${Math.round(clampedProgress)}%`}
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
            <stop offset="0%" stopColor={getMetricAccentColor(accent)} />
            <stop offset="100%" stopColor={getMetricAccentColor(accent, 0.72)} />
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

/**
 * 2026-04-21，任务：仪表盘组件视觉重构
 * 修改原因：让评分圆点与卡片壳使用同一套 accent 色，避免局部控件仍停留在旧视觉语言里
 */
function DotRating({
  score,
  accent,
  maxScore = 5,
}: {
  score: number;
  accent: MetricAccent;
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
            fill={i < score ? getMetricAccentColor(accent) : "hsl(var(--border))"}
          />
        </motion.svg>
      ))}
    </div>
  );
}

/**
 * 2026-04-21，任务：仪表盘组件视觉重构
 * 修改原因：统一评分行的布局与强调色传递，支撑新的仪表盘卡片壳
 */
function ScoreRow({
  label,
  score,
  accent,
  maxScore = 5,
}: {
  label: string;
  score?: number | null;
  accent: MetricAccent;
  maxScore?: number;
}) {
  if (score == null) {
    return (
      <div className="flex items-center justify-between">
        <span className="text-xs text-text-muted">{label}</span>
        <span className="text-xs text-text-muted">{formatSampleInsufficient()}</span>
      </div>
    );
  }

  const clampedScore = Math.max(0, Math.min(maxScore, score));

  return (
    <div className="flex items-center justify-between">
      <span className="text-xs text-text-muted">{label}</span>
      <div className="flex items-center gap-2">
        <DotRating score={clampedScore} accent={accent} maxScore={maxScore} />
        <span className="text-xs font-medium tabular-nums text-text">
          {clampedScore}/{maxScore}
        </span>
      </div>
    </div>
  );
}

/**
 * 2026-04-21，任务：仪表盘组件视觉重构
 * 修改原因：让评分速览卡复用共享卡片壳，和展示页中的强调色、图标色块、hover 反馈保持一致
 */
export function ScoreOverviewCard({
  foreshadowExpectation,
  powerStance,
  civilianDignity,
  culturalDepth,
  novelId,
  className,
}: ScoreOverviewCardProps) {
  const navigate = useNavigate();
  const accent: MetricAccent = "chart-2";

  const foreshadowPct =
    foreshadowExpectation != null ? Math.round(foreshadowExpectation * 100) : null;

  return (
    <DashboardCardShell
      title="评分速览"
      icon={<BarChart3 className="h-5 w-5" />}
      accent={accent}
      showOrb
      className={cn(className)}
      bodyClassName="gap-3"
      footer={
        <Button
          variant="ghost"
          size="sm"
          onClick={() => navigate(`/novels/${novelId}/diagnosis`)}
          className={cn(
            "group flex items-center gap-1 px-0 text-xs text-text-muted transition-colors",
            getMetricAccentHoverTextClass(accent)
          )}
        >
          查看完整诊断报告
          <ArrowRight className="h-3 w-3 transition-transform group-hover:translate-x-0.5" />
        </Button>
      }
    >
        <div className="rounded-2xl border border-chart-2/15 bg-surface/75 p-3.5 shadow-sm">
          <div className="flex items-center gap-3">
          {foreshadowPct != null ? (
            <>
              <MiniProgressRing progress={foreshadowPct} accent={accent} />
              <div>
                <p className="text-xs uppercase tracking-wide text-text-muted">伏笔回收预期</p>
                <p className="text-lg font-semibold tabular-nums text-text">{foreshadowPct}%</p>
              </div>
            </>
          ) : (
            <div className="flex items-center gap-3">
              <div
                className="flex h-12 w-12 items-center justify-center rounded-full border"
                style={{
                  backgroundColor: getMetricAccentColor(accent, 0.08),
                  borderColor: getMetricAccentColor(accent, 0.18),
                }}
              >
                <span className="text-xs text-text-muted">—</span>
              </div>
              <div>
                <p className="text-xs uppercase tracking-wide text-text-muted">伏笔回收预期</p>
                <p className="text-sm text-text-muted">{formatSampleInsufficient()}</p>
              </div>
            </div>
          )}
        </div>
        </div>

        <div className="rounded-2xl border border-border/70 bg-surface/70 p-3.5">
          <div className="mb-2 text-xs uppercase tracking-wide text-text-muted">核心评分</div>
          <div className="flex flex-col gap-2.5">
            <ScoreRow label="权力立场" score={powerStance} accent={accent} />
            <ScoreRow label="平民尊严" score={civilianDignity} accent={accent} />
            <ScoreRow label="文化深度" score={culturalDepth} accent={accent} />
          </div>
        </div>
    </DashboardCardShell>
  );
}
