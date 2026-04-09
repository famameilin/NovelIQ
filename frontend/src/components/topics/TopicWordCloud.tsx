/**
 * TopicWordCloud - 关键词词云组件
 *
 * 创建时间: 2026-04-05
 * 创建者: GLM-5
 * 任务: Phase 2-C 主题分布
 * 说明: 基于 ECharts wordcloud 的词云图，词大小映射权重，颜色映射所属主题
 */
import { useMemo } from "react";
import ReactEChartsCore from "echarts-for-react";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import { Card, CardContent } from "@/components/ui/card";
import { getCSSColorVar } from "@/lib/theme";
import { CHART_COLORS } from "@/lib/chart-colors";
import { cn } from "@/lib/cn";
import { useInView } from "@/hooks/useInView";
import type { Topic } from "@/api/types";

import "echarts-wordcloud";

echarts.use([CanvasRenderer]);

interface WordCloudData {
  name: string;
  value: number;
  topicId: number;
  topicLabel: string;
}

export interface TopicWordCloudProps {
  topics: Topic[];
  maxWords?: number;
  className?: string;
}

export function TopicWordCloud({
  topics,
  maxWords = 100,
  className,
}: TopicWordCloudProps) {
  const { ref: containerRef, isVisible } = useInView(0.1);

  const chartColors = useMemo(() => {
    return CHART_COLORS.map((c) => getCSSColorVar(c));
  }, []);

  const wordData = useMemo((): WordCloudData[] => {
    // 记录每个词来自各主题的贡献，用于确定主属主题
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
        } else {
          wordMap.set(word, {
            count: weightedValue,
            contributions: [{ topicId: topic.topic_id, topicLabel, value: weightedValue }],
          });
        }
      });
    });

    return Array.from(wordMap.entries())
      .map(([name, data]) => {
        // 选择贡献最大的主题作为该词的主属主题
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

  const option = useMemo(() => {
    if (wordData.length === 0) return {};

    return {
      tooltip: {
        show: true,
        backgroundColor: "hsl(var(--surface))",
        borderColor: "hsl(var(--border))",
        textStyle: { color: "hsl(var(--text))", fontSize: 12 },
        formatter: (params: { data: WordCloudData }) => {
          const d = params.data;
          return `<div>
            <div style="font-weight: 600">${d.name}</div>
            <div style="color: hsl(var(--text-muted)); font-size: 11px">所属: ${d.topicLabel}</div>
          </div>`;
        },
      },
      series: [
        {
          type: "wordCloud",
          shape: "circle" as const,
          left: "center" as const,
          top: "center" as const,
          width: "90%" as const,
          height: "90%" as const,
          sizeRange: [12, 48] as [number, number],
          rotationRange: [0, 90] as [number, number],
          rotationStep: 90 as number,
          gridSize: 8 as number,
          drawOutOfBound: false as boolean,
          textStyle: {
            fontFamily: "system-ui, sans-serif",
            fontWeight: 500,
          },
          emphasis: {
            textStyle: {
              fontWeight: 700,
            },
          },
          data: wordData.map((d) => ({
            name: d.name,
            value: d.value,
            topicId: d.topicId,
            topicLabel: d.topicLabel,
            textStyle: {
              color: chartColors[d.topicId % chartColors.length],
            },
          })),
        },
      ],
    };
  }, [wordData, chartColors]);

  const hasData = wordData.length > 0;

  return (
    <Card variant="elevated" className={cn("rounded-xl overflow-hidden", className)}>
      <CardContent className="flex flex-col gap-3 p-5">
        <h4 className="text-sm font-semibold text-text">关键词词云</h4>

        <div ref={containerRef} className="h-[300px] w-full">
          {hasData && isVisible ? (
            <ReactEChartsCore
              echarts={echarts}
              option={option}
              style={{ height: "100%", width: "100%" }}
              notMerge
              lazyUpdate
            />
          ) : (
            <div className="flex h-full items-center justify-center text-sm text-text-muted">
              {hasData ? "加载中..." : "暂无关键词数据"}
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
