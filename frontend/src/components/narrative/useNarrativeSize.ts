import { useEffect, useRef, useState } from "react";

/** 只测量本页可视容器，章节坐标不随筛选后的记录数量变化 */
export function useNarrativeSize(defaultWidth = 1000) {
  const ref = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ width: defaultWidth, height: 650 });
  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      if (width > 0) setSize(previous => previous.width === width && previous.height === height ? previous : { width, height });
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  return [ref, size] as const;
}
