import { Button } from "@/components/ui/button";

interface PagedControlsProps {
  page: number;
  pageCount: number;
  onPageChange: (page: number) => void;
  label: string;
}

/** Keep long analysis collections navigable without adding a scroll pane to a single-screen tab. */
export function PagedControls({ page, pageCount, onPageChange, label }: PagedControlsProps) {
  if (pageCount <= 1) return null;

  return (
    <nav aria-label={`${label}分页`} className="flex shrink-0 items-center justify-end gap-3 text-xs text-text-muted">
      <span>{label} {page} / {pageCount}</span>
      <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => onPageChange(page - 1)}>
        上一页
      </Button>
      <Button variant="outline" size="sm" disabled={page >= pageCount} onClick={() => onPageChange(page + 1)}>
        下一页
      </Button>
    </nav>
  );
}
