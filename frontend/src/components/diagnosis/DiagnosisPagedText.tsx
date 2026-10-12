import { useLayoutEffect, useRef, useState } from "react";
import { PagedControls } from "@/components/common/PagedControls";
import { paginateText } from "@/lib/paginateText";
import { cn } from "@/lib/cn";

interface DiagnosisPagedTextProps {
  text?: string | null;
  label: string;
  emptyText?: string;
  testId?: string;
  className?: string;
}

/** 用同字体的临时测量节点寻找可容纳的完整片段，分页不丢弃字符 */
function fitPassages(element: HTMLElement, text: string): string[] {
  if (!element.clientWidth || !element.clientHeight) return paginateText(text, 180);
  const style = getComputedStyle(element);
  const probe = document.createElement("div");
  Object.assign(probe.style, {
    position: "fixed", visibility: "hidden", pointerEvents: "none", left: "0", top: "0",
    // clientWidth 会取整，分数列宽被向上取整后可能少算一整行
    width: `${element.getBoundingClientRect().width - 0.05}px`, margin: "0", padding: "0",
    fontFamily: style.fontFamily, fontSize: style.fontSize, fontWeight: style.fontWeight,
    fontStyle: style.fontStyle, lineHeight: style.lineHeight, letterSpacing: style.letterSpacing,
    whiteSpace: "pre-wrap", overflowWrap: "anywhere",
  });
  document.body.append(probe);
  const characters = Array.from(text);
  const pages: string[] = [];
  try {
    const availableHeight = Math.floor((element.parentElement ?? element).getBoundingClientRect().height);
    probe.textContent = text;
    // 单页文字不保留空页脚；仅多页时为分页控件和间距扣除 40 像素
    if (probe.getBoundingClientRect().height <= availableHeight - 1) return text ? [text] : [];
    const passageHeight = availableHeight - 40;
    let start = 0;
    while (start < characters.length) {
      let low = start + 1, high = characters.length, end = start + 1;
      while (low <= high) {
        const middle = Math.floor((low + high) / 2);
        probe.textContent = characters.slice(start, middle).join("");
        if (probe.getBoundingClientRect().height <= passageHeight - 1) {
          end = middle;
          low = middle + 1;
        } else high = middle - 1;
      }
      // 接近页尾时优先保留句子边界，避免每次翻页都从半句话开始
      if (end < characters.length) {
        const earliest = start + Math.floor((end - start) * 0.75);
        for (let index = end - 1; index >= earliest; index--) {
          if (/[。！？；\n]/u.test(characters[index])) { end = index + 1; break; }
        }
      }
      pages.push(characters.slice(start, end).join(""));
      start = end;
    }
  } finally { probe.remove(); }
  return pages;
}

/** 正文在分配到的区域内分页，页脚预留真实控件高度，禁止裁切或滚动 */
export function DiagnosisPagedText({ text, label, emptyText = "暂无补充依据", testId, className }: DiagnosisPagedTextProps) {
  const ref = useRef<HTMLDivElement>(null);
  const [passages, setPassages] = useState<string[]>([]);
  const [page, setPage] = useState(1);
  const source = text?.trim() || "";
  useLayoutEffect(() => {
    const element = ref.current;
    if (!element) return;
    function measure() {
      if (!element) return;
      const next = fitPassages(element, source);
      setPassages(current => current.length === next.length && current.every((item, index) => item === next[index]) ? current : next);
    }
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [source]);
  const currentPage = Math.min(page, Math.max(passages.length, 1));
  return (
    <div className="flex h-full min-h-0 flex-1 flex-col gap-2" data-testid="diagnosis-text-reader">
      <div ref={ref} data-testid={testId} className={cn("min-h-0 flex-1 whitespace-pre-wrap text-sm leading-6 text-text-muted [overflow-wrap:anywhere]", className)}>
        {source ? passages[currentPage - 1] : emptyText}
      </div>
      {passages.length > 1 && <div className="h-8 shrink-0">
        <PagedControls page={currentPage} pageCount={passages.length} onPageChange={setPage} label={label} />
      </div>}
    </div>
  );
}
