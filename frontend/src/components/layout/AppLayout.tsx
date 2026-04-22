import { createContext, useContext, useState, useCallback, useEffect } from "react";
import { Outlet } from "react-router-dom";
import { TopBar } from "./TopBar";
import { SideNav } from "./SideNav";
import { HeroPanel } from "./HeroPanel";
import type { LayoutMode } from "./types";
import { useNovelStore } from "@/store/novelStore";
import { useNovelTheme } from "@/hooks/useNovelTheme";

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
  useNovelTheme();

  const [total, setTotal] = useState(0);
  const [isLoading, setIsLoading] = useState(false);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [uploadDialogOpen, setUploadDialogOpen] = useState(false);

  const openUploadDialog = useCallback(() => setUploadDialogOpen(true), []);
  const closeUploadDialog = useCallback(() => setUploadDialogOpen(false), []);

  /**
   * 修改时间: 2026-04-22
   * 任务: 修复首页误继承任务主题色
   * 修改原因: 首页不对应具体小说任务；进入首页布局时需要清空当前小说/任务选择，
   * 避免全局主题 hook 继续沿用上一次任务的 diagnosis 主题色。
   */
  useEffect(() => {
    if (mode !== "with-hero-panel") {
      return;
    }

    const { currentNovelId, currentTaskId } = useNovelStore.getState();
    if (!currentNovelId && !currentTaskId) {
      return;
    }

    useNovelStore.setState({
      currentNovelId: null,
      currentTaskId: null,
    });
  }, [mode]);

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
