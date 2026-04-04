/**
 * useCountUp - 数字动画 Hook
 * 
 * 创建时间: 2026-04-04
 * 创建者: AI Assistant
 * 任务: Sprint 1-A UI 组件
 * 说明: 数字从 start 到 value 的动画过渡
 * 
 * 修改时间: 2026-04-04
 * 修改者: AI Assistant
 * 修改内容: 修复 effect 中同步调用 setState 的警告
 */
import { useEffect, useRef, useState } from "react";

interface UseCountUpOptions {
  start?: number;
  duration?: number;
  decimals?: number;
  enabled?: boolean;
}

export function useCountUp(
  value: number,
  options: UseCountUpOptions = {}
) {
  const { start = 0, duration = 600, decimals = 0, enabled = true } = options;

  const [displayValue, setDisplayValue] = useState(start);
  const rafRef = useRef<number | null>(null);
  const prevEnabledRef = useRef(enabled);

  useEffect(() => {
    if (!enabled) {
      if (prevEnabledRef.current) {
        // eslint-disable-next-line react-hooks/set-state-in-effect
        setDisplayValue(start);
      }
      prevEnabledRef.current = false;
      return;
    }

    prevEnabledRef.current = true;

    let startTime: number | null = null;
    let cancelled = false;

    const animate = (timestamp: number) => {
      if (cancelled) return;
      if (!startTime) startTime = timestamp;
      const elapsed = timestamp - startTime;
      const progress = Math.min(elapsed / duration, 1);
      const easeOut = 1 - Math.pow(1 - progress, 3);
      const current = start + (value - start) * easeOut;

      setDisplayValue(current);

      if (progress < 1) {
        rafRef.current = requestAnimationFrame(animate);
      } else {
        setDisplayValue(value);
      }
    };

    rafRef.current = requestAnimationFrame(animate);

    return () => {
      cancelled = true;
      if (rafRef.current) {
        cancelAnimationFrame(rafRef.current);
      }
    };
  }, [enabled, value, start, duration]);

  return decimals > 0 ? displayValue.toFixed(decimals) : String(Math.round(displayValue));
}
