import { useLayoutEffect, useRef, useState } from "react";

/** 按桌面工作区实际高度分配条目，不借助窗口宽度或滚动容器 */
export function useDiagnosisCapacity(rowHeight: number, reservedHeight = 0, initial = 12) {
  const ref = useRef<HTMLDivElement>(null);
  const [capacity, setCapacity] = useState(initial);

  useLayoutEffect(() => {
    const element = ref.current;
    if (!element) return;
    function measure() {
      if (!element || element.clientHeight === 0) return;
      setCapacity(Math.max(1, Math.floor((element.clientHeight - reservedHeight) / rowHeight)));
    }
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [rowHeight, reservedHeight]);

  return { ref, capacity };
}
