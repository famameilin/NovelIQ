import { createContext, useContext, useState, useCallback } from "react";
import { Outlet } from "react-router-dom";
import { TopBar } from "./TopBar";
import { SideNav } from "./SideNav";
import { HeroPanel } from "./HeroPanel";
import type { LayoutMode } from "./types";

interface AppLayoutProps {
  mode?: LayoutMode;
}

interface HomeContextValue {
  total: number;
  isLoading: boolean;
  page: number;
  totalPages: number;
  uploadDialogOpen: boolean;
  setTotal: (total: number) => void;
  setIsLoading: (isLoading: boolean) => void;
  setPage: (page: number) => void;
  setTotalPages: (totalPages: number) => void;
  openUploadDialog: () => void;
  closeUploadDialog: () => void;
}

const HomeContext = createContext<HomeContextValue | null>(null);

export function useHomeContext() {
  const ctx = useContext(HomeContext);
  return ctx;
}

export function AppLayout({ mode = "default" }: AppLayoutProps) {
  const [total, setTotal] = useState(0);
  const [isLoading, setIsLoading] = useState(false);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [uploadDialogOpen, setUploadDialogOpen] = useState(false);

  const openUploadDialog = useCallback(() => setUploadDialogOpen(true), []);
  const closeUploadDialog = useCallback(() => setUploadDialogOpen(false), []);

  const homeContextValue: HomeContextValue = {
    total,
    isLoading,
    page,
    totalPages,
    uploadDialogOpen,
    setTotal,
    setIsLoading,
    setPage,
    setTotalPages,
    openUploadDialog,
    closeUploadDialog,
  };

  return (
    <div className="flex h-screen flex-col bg-background">
      <TopBar />
      <div className="flex flex-1 overflow-hidden">
        {mode === "with-side-nav" && <SideNav />}
        {mode === "with-hero-panel" ? (
          <HomeContext.Provider value={homeContextValue}>
            <HeroPanel
              total={total}
              isLoading={isLoading}
              onUpload={openUploadDialog}
              page={page}
              totalPages={totalPages}
              onPageChange={setPage}
            />
            <div className="flex-1 overflow-y-auto">
              <Outlet />
            </div>
          </HomeContext.Provider>
        ) : (
          <div className="flex-1 overflow-y-auto">
            <Outlet />
          </div>
        )}
      </div>
    </div>
  );
}
