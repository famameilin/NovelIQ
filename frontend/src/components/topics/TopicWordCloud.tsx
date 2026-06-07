/**
 * TopicWordCloud - 关键词词云组件
 *
 * 2026-04-30，任务：替换 frontend 中与 echarts@6 冲突的 echarts-wordcloud
 * 修改原因：保持 TopicWordCloud 的外部 props 和页面交互基本不变，同时移除 Docker 构建中的 peer dependency 冲突
 */
import { useEffect, useMemo, useState } from "react";
import type { PointerEvent as ReactPointerEvent } from "react";
import { Tags } from "lucide-react";
import { DashboardCardShell } from "@/components/common/DashboardCardShell";
import { getCSSColorVar } from "@/lib/theme";
import { CHART_COLORS } from "@/lib/chart-colors";
import { cn } from "@/lib/cn";
import { useChartThemeSignature } from "@/hooks/useChartThemeSignature";
import { useInView } from "@/hooks/useInView";
import type { Topic } from "@/api/types";

interface WordCloudData {
  name: string;
  value: number;
  topicId: number;
  topicLabel: string;
}

interface LayoutWord extends WordCloudData {
  text: string;
  size: number;
  color: string;
  x?: number;
  y?: number;
  rotate?: number;
}

interface LayoutBoundsPoint {
  x: number;
  y: number;
}

type LayoutBounds = [LayoutBoundsPoint, LayoutBoundsPoint] | null;

interface CloudLayout<TWord> {
  size(value: [number, number]): CloudLayout<TWord>;
  words(value: TWord[]): CloudLayout<TWord>;
  padding(value: number): CloudLayout<TWord>;
  rotate(value: (word: TWord) => number): CloudLayout<TWord>;
  font(value: string): CloudLayout<TWord>;
  fontSize(value: (word: TWord) => number): CloudLayout<TWord>;
  random(value: () => number): CloudLayout<TWord>;
  on(eventName: "end", handler: (words: TWord[], bounds: LayoutBounds) => void): CloudLayout<TWord>;
  start(): void;
  stop(): void;
}

export interface TopicWordCloudProps {
  topics: Topic[];
  maxWords?: number;
  className?: string;
}

interface TooltipState {
  word: LayoutWord;
  x: number;
  y: number;
}

const MIN_FONT_SIZE = 12;
const MAX_FONT_SIZE = 48;
const FALLBACK_WIDTH = 320;
const FALLBACK_HEIGHT = 300;

/**
 * 2026-04-30，任务：替换 frontend 词云布局库
 * 新建原因：词云布局需要稳定的线性映射，避免在更换底层库后出现字号飘忽
 */
function scaleWordSize(value: number, minValue: number, maxValue: number) {
  if (maxValue <= minValue) {
    return (MIN_FONT_SIZE + MAX_FONT_SIZE) / 2;
  }

  const ratio = (value - minValue) / (maxValue - minValue);
  return MIN_FONT_SIZE + ratio * (MAX_FONT_SIZE - MIN_FONT_SIZE);
}

/**
 * 2026-04-30，任务：替换 frontend 词云布局库
 * 新建原因：d3-cloud 允许注入随机数生成器，这里固定种子以减少同一批数据反复抖动
 */
function createSeededRandom(seedSource: string) {
  let seed = 0;

  for (const char of seedSource) {
    seed = (seed * 31 + char.charCodeAt(0)) >>> 0;
  }

  return () => {
    seed = (seed * 1664525 + 1013904223) >>> 0;
    return seed / 0x100000000;
  };
}

/**
 * 2026-04-30，任务：替换 frontend 词云布局库
 * 新建原因：保留原先 0/90 度旋转的视觉风格，但改成与词本身绑定的稳定结果
 */
function getWordRotation(word: Pick<LayoutWord, "name">) {
  let hash = 0;

  for (const char of word.name) {
    hash = (hash * 33 + char.charCodeAt(0)) >>> 0;
  }

  return hash % 2 === 0 ? 0 : 90;
}

/**
 * 2026-04-30，任务：替换 frontend 词云布局库
 * 新建原因：统一把容器尺寸兜底到可布局的范围，避免首帧测量为 0 时直接跳空
 */
function resolveContainerSize(element: HTMLDivElement) {
  return {
    width: Math.max(element.clientWidth, FALLBACK_WIDTH),
    height: Math.max(element.clientHeight, FALLBACK_HEIGHT),
  };
}

/**
 * 2026-04-28，任务：分析详情页单屏 Tabs 改造
 * 2026-04-30，任务：替换 frontend 中与 echarts@6 冲突的 echarts-wordcloud
 * 修改原因：主题词云需要在统一 tab 工作区内填满可用高度，同时保留独立使用时的最小高度，并维持原有数据入口
 */
export function TopicWordCloud({
  topics,
  maxWords = 100,
  className,
}: TopicWordCloudProps) {
  const themeSignature = useChartThemeSignature();
  const { ref: containerRef, isVisible } = useInView(0.1);
  const [containerSize, setContainerSize] = useState({ width: 0, height: 0 });
  const [placedWords, setPlacedWords] = useState<LayoutWord[]>([]);
  const [layoutCompleted, setLayoutCompleted] = useState(false);
  const [layoutError, setLayoutError] = useState(false);
  const [tooltip, setTooltip] = useState<TooltipState | null>(null);

  const chartColors = useMemo(() => {
    return CHART_COLORS.map((c) => getCSSColorVar(c));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- themeSignature triggers re-computation on theme change
  }, [themeSignature]);

  const wordData = useMemo((): WordCloudData[] => {
    interface WordContribution {
      count: number;
      contributions: Array<{ topicId: number; topicLabel: string; value: number }>;
    }

    const wordMap = new Map<string, WordContribution>();

    topics.forEach((topic) => {
      const topicLabel = topic.label || `主题 ${topic.topic_id + 1}`;
      topic.words.forEach((word, index) => {
        const positionWeight = topic.words.length - index;
        const weightedValue = topic.weight * positionWeight;
        const existing = wordMap.get(word);

        if (existing) {
          existing.count += weightedValue;
          existing.contributions.push({ topicId: topic.topic_id, topicLabel, value: weightedValue });
          return;
        }

        wordMap.set(word, {
          count: weightedValue,
          contributions: [{ topicId: topic.topic_id, topicLabel, value: weightedValue }],
        });
      });
    });

    return Array.from(wordMap.entries())
      .map(([name, data]) => {
        // 保留“贡献最大主题决定颜色”的旧语义，避免主题词颜色漂移。
        const primary = data.contributions.reduce((best, curr) =>
          curr.value > best.value ? curr : best
        );

        return {
          name,
          value: data.count,
          topicId: primary.topicId,
          topicLabel: primary.topicLabel,
        };
      })
      .sort((a, b) => b.value - a.value)
      .slice(0, maxWords);
  }, [topics, maxWords]);

  const layoutWords = useMemo((): LayoutWord[] => {
    if (wordData.length === 0) {
      return [];
    }

    const values = wordData.map((word) => word.value);
    const minValue = Math.min(...values);
    const maxValue = Math.max(...values);

    return wordData.map((word) => ({
      ...word,
      text: word.name,
      size: scaleWordSize(word.value, minValue, maxValue),
      color: chartColors[word.topicId % chartColors.length],
    }));
  }, [chartColors, wordData]);

  useEffect(() => {
    const element = containerRef.current;

    if (!element) {
      return;
    }

    const updateSize = () => {
      setContainerSize(resolveContainerSize(element));
    };

    updateSize();

    const observer = new ResizeObserver(() => {
      updateSize();
    });

    observer.observe(element);
    return () => observer.disconnect();
  }, [containerRef]);

  useEffect(() => {
    if (!isVisible || layoutWords.length === 0) {
      setPlacedWords([]);
      setLayoutCompleted(false);
      setTooltip(null);
      setLayoutError(false);
      return;
    }

    if (containerSize.width === 0 || containerSize.height === 0) {
      return;
    }

    let cancelled = false;
    let cloudLayout: CloudLayout<LayoutWord> | null = null;

    const buildLayout = async () => {
      setLayoutError(false);
      setLayoutCompleted(false);
      setPlacedWords([]);

      const random = createSeededRandom(
        layoutWords.map((word) => `${word.name}:${word.value}:${word.topicId}`).join("|")
      );

      try {
        const cloudModule = (await import("d3-cloud")) as { default: <TWord>() => CloudLayout<TWord> };

        if (cancelled) {
          return;
        }

        cloudLayout = cloudModule.default<LayoutWord>()
          .size([containerSize.width, containerSize.height])
          .words(layoutWords)
          .padding(6)
          .rotate((word) => getWordRotation(word))
          .font("system-ui, sans-serif")
          .fontSize((word) => word.size)
          .random(random)
          .on("end", (words) => {
            if (cancelled) {
              return;
            }

            setPlacedWords(words);
            setLayoutCompleted(true);
            setLayoutError(words.length === 0);
          });

        cloudLayout.start();
      } catch (error) {
        if (cancelled) {
          return;
        }

        console.error("Failed to render topic word cloud", error);
        setLayoutCompleted(true);
        setLayoutError(true);
      }
    };

    void buildLayout();

    return () => {
      cancelled = true;
      cloudLayout?.stop();
    };
  }, [containerSize.height, containerSize.width, isVisible, layoutWords]);

  const hasData = wordData.length > 0;
  const isLayoutReady = placedWords.length > 0;

  /**
   * 2026-04-30，任务：替换 frontend 词云布局库
   * 新建原因：保留词云 hover 提示语义，并继续显示“所属主题”信息
   */
  const handleWordPointerMove = (event: ReactPointerEvent<SVGTextElement>, word: LayoutWord) => {
    const containerRect = containerRef.current?.getBoundingClientRect();

    if (!containerRect) {
      return;
    }

    setTooltip({
      word,
      x: event.clientX - containerRect.left + 12,
      y: event.clientY - containerRect.top + 12,
    });
  };

  /**
   * 2026-04-30，任务：替换 frontend 词云布局库
   * 新建原因：在 SVG 文本离开时及时清理 tooltip，避免残留在卡片上
   */
  const handleWordPointerLeave = () => {
    setTooltip(null);
  };

  return (
    <DashboardCardShell
      title="关键词词云"
      icon={<Tags className="h-4 w-4" />}
      accent="chart-3"
      showOrb
      className={cn(className)}
      contentClassName="flex h-full flex-col"
      bodyClassName="min-h-0 flex-1 gap-3"
    >
      <div
        ref={containerRef}
        className="relative min-h-[300px] flex-1 w-full rounded-2xl border border-border/60 bg-surface/70 p-2"
      >
        {hasData && isVisible && isLayoutReady ? (
          <>
            <svg
              key={themeSignature}
              width="100%"
              height="100%"
              viewBox={`0 0 ${containerSize.width || FALLBACK_WIDTH} ${containerSize.height || FALLBACK_HEIGHT}`}
              className="block h-full w-full"
              aria-label="关键词词云图"
            >
              <g transform={`translate(${(containerSize.width || FALLBACK_WIDTH) / 2}, ${(containerSize.height || FALLBACK_HEIGHT) / 2})`}>
                {placedWords.map((word) => (
                  <text
                    key={`${word.name}-${word.topicId}`}
                    x={word.x ?? 0}
                    y={word.y ?? 0}
                    transform={`rotate(${word.rotate ?? 0}, ${word.x ?? 0}, ${word.y ?? 0})`}
                    textAnchor="middle"
                    dominantBaseline="middle"
                    fontSize={word.size}
                    fontFamily="system-ui, sans-serif"
                    fontWeight={word.rotate === 0 ? 500 : 600}
                    fill={word.color}
                    className="cursor-default select-none transition-opacity duration-150 hover:opacity-80"
                    onPointerMove={(event) => handleWordPointerMove(event, word)}
                    onPointerLeave={handleWordPointerLeave}
                  >
                    {word.name}
                  </text>
                ))}
              </g>
            </svg>

            {tooltip ? (
              <div
                className="pointer-events-none absolute z-10 rounded-lg border border-border bg-surface px-3 py-2 text-xs shadow-lg"
                style={{
                  left: tooltip.x,
                  top: tooltip.y,
                  maxWidth: "220px",
                }}
              >
                <div className="font-semibold text-text">{tooltip.word.name}</div>
                <div className="text-text-muted">所属: {tooltip.word.topicLabel}</div>
              </div>
            ) : null}
          </>
        ) : (
          <div className="flex h-full items-center justify-center text-sm text-text-muted">
            {!hasData ? "暂无关键词数据" : layoutError || layoutCompleted ? "词云加载失败" : "加载中..."}
          </div>
        )}
      </div>
    </DashboardCardShell>
  );
}
