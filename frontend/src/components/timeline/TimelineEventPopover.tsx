import { useEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";

interface TimelineEventPopoverProps {
  anchor: HTMLElement | null;
  children: ReactNode;
  onClose: () => void;
}

interface PopoverPosition {
  left: number;
  top: number;
  width: number;
  height: number;
}

/** 悬浮详情脱离横向滚动容器，靠近所点卡片并始终留在视口内 */
function getPopoverPosition(anchor: HTMLElement | null): PopoverPosition {
  const inset = 16;
  const width = Math.min(700, window.innerWidth - inset * 2);
  const height = Math.min(580, window.innerHeight - inset * 2);
  const maxLeft = window.innerWidth - width - inset;
  const maxTop = window.innerHeight - height - inset;
  const rect = anchor?.getBoundingClientRect();
  const visibleAnchor = rect && rect.right > 0 && rect.left < window.innerWidth &&
    rect.bottom > 0 && rect.top < window.innerHeight;
  let left = (window.innerWidth - width) / 2;
  let top = (window.innerHeight - height) / 2;

  if (visibleAnchor) {
    if (rect.right + 12 + width <= window.innerWidth - inset) left = rect.right + 12;
    else if (rect.left - 12 - width >= inset) left = rect.left - 12 - width;
    else left = rect.left + rect.width / 2 - width / 2;
    top = rect.top + rect.height / 2 - height / 2;
  }

  return {
    left: Math.max(inset, Math.min(left, maxLeft)),
    top: Math.max(Math.min(72, maxTop), Math.min(top, maxTop)),
    width,
    height,
  };
}

export function TimelineEventPopover({ anchor, children, onClose }: TimelineEventPopoverProps) {
  const panelRef = useRef<HTMLDivElement>(null);
  const [, setViewportRevision] = useState(0);
  const position = getPopoverPosition(anchor);

  useEffect(() => {
    const updatePosition = () => setViewportRevision((value) => value + 1);
    window.addEventListener("resize", updatePosition);
    window.addEventListener("scroll", updatePosition, true);
    return () => {
      window.removeEventListener("resize", updatePosition);
      window.removeEventListener("scroll", updatePosition, true);
    };
  }, []);

  useEffect(() => {
    panelRef.current?.focus();
    const handlePointerDown = (event: PointerEvent) => {
      const target = event.target;
      if (!(target instanceof Node) || panelRef.current?.contains(target)) return;
      // 点击另一张事件卡时交给卡片本身切换选中事件
      if (target instanceof Element && target.closest('[data-testid="timeline-card"], [aria-label="时间轴筛选"]')) return;
      onClose();
    };
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("pointerdown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [onClose]);

  return createPortal(
    <div
      ref={panelRef}
      role="dialog"
      aria-label="事件详情悬浮框"
      aria-modal="false"
      tabIndex={-1}
      data-testid="timeline-event-popup"
      className="fixed z-[100] rounded-xl bg-background shadow-[0_24px_70px_rgba(57,35,31,0.28)] outline-none"
      style={position}
    >
      {children}
    </div>,
    document.body,
  );
}
