/* eslint-disable react-refresh/only-export-components -- lazy route definitions */
import { lazy, Suspense } from "react";
import { createBrowserRouter } from "react-router-dom";
import { AppLayout } from "@/components/layout/AppLayout";

// 懒加载页面组件
const HomePage = lazy(() => import("@/pages/HomePage").then((m) => ({ default: m.HomePage })));
const NovelDetailPage = lazy(() => import("@/pages/NovelDetailPage").then((m) => ({ default: m.NovelDetailPage })));
const CurvesPage = lazy(() => import("@/pages/CurvesPage").then((m) => ({ default: m.CurvesPage })));
const CharactersPage = lazy(() => import("@/pages/CharactersPage").then((m) => ({ default: m.CharactersPage })));
const GraphPage = lazy(() => import("@/pages/GraphPage").then((m) => ({ default: m.GraphPage })));
const TopicsPage = lazy(() => import("@/pages/TopicsPage").then((m) => ({ default: m.TopicsPage })));
const TimelinePage = lazy(() => import("@/pages/TimelinePage").then((m) => ({ default: m.TimelinePage })));
const DiagnosisPage = lazy(() => import("@/pages/DiagnosisPage").then((m) => ({ default: m.DiagnosisPage })));
const NotFoundPage = lazy(() => import("@/pages/NotFoundPage").then((m) => ({ default: m.NotFoundPage })));
const ComponentShowcase = lazy(() => import("@/pages/ComponentShowcase").then((m) => ({ default: m.ComponentShowcase })));

// 懒加载页面共用骨架屏
function PageSkeleton() {
  return (
    <div className="flex h-full items-center justify-center">
      <div className="h-8 w-8 animate-spin rounded-full border-2 border-primary border-t-transparent" />
    </div>
  );
}

function withSuspense(Component: React.LazyExoticComponent<React.ComponentType>) {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <Component />
    </Suspense>
  );
}

export const router = createBrowserRouter([
  {
    element: <AppLayout mode="with-hero-panel" />,
    children: [
      { path: "/", element: withSuspense(HomePage) },
    ],
  },
  {
    element: <AppLayout mode="with-side-nav" />,
    children: [
      { path: "/novels/:novelId", element: withSuspense(NovelDetailPage) },
      { path: "/novels/:novelId/curves", element: withSuspense(CurvesPage) },
      { path: "/novels/:novelId/characters", element: withSuspense(CharactersPage) },
      { path: "/novels/:novelId/graph", element: withSuspense(GraphPage) },
      { path: "/novels/:novelId/topics", element: withSuspense(TopicsPage) },
      { path: "/novels/:novelId/timeline", element: withSuspense(TimelinePage) },
      { path: "/novels/:novelId/diagnosis", element: withSuspense(DiagnosisPage) },
    ],
  },
  {
    element: <AppLayout mode="default" />,
    children: [
      { path: "/dev/components", element: withSuspense(ComponentShowcase) },
    ],
  },
  { path: "*", element: withSuspense(NotFoundPage) },
]);
