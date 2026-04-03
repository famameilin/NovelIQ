export type LayoutMode = "default" | "with-side-nav" | "with-hero-panel";

export interface AppLayoutProps {
  mode?: LayoutMode;
}

export interface HeroPanelProps {
  total: number;
  isLoading?: boolean;
  onUpload: () => void;
  page?: number;
  totalPages?: number;
  onPageChange?: (page: number) => void;
}
