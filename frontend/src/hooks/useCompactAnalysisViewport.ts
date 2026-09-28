import { useEffect, useState } from "react";

const COMPACT_QUERY = "(max-height: 850px)";

/** Keep paginated analysis content inside a shorter desktop viewport. */
export function useCompactAnalysisViewport(): boolean {
  const [compact, setCompact] = useState(() =>
    typeof window !== "undefined" && typeof window.matchMedia === "function"
      ? window.matchMedia(COMPACT_QUERY).matches
      : false,
  );

  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const query = window.matchMedia(COMPACT_QUERY);
    const onChange = () => setCompact(query.matches);
    query.addEventListener("change", onChange);
    onChange();
    return () => query.removeEventListener("change", onChange);
  }, []);

  return compact;
}
