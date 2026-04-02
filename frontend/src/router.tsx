import { createBrowserRouter } from "react-router-dom";
import { AppLayout } from "@/components/layout/AppLayout";
import { HomePage } from "@/pages/HomePage";
import { NovelDetailPage } from "@/pages/NovelDetailPage";
import { CurvesPage } from "@/pages/CurvesPage";
import { CharactersPage } from "@/pages/CharactersPage";
import { GraphPage } from "@/pages/GraphPage";
import { TopicsPage } from "@/pages/TopicsPage";
import { TimelinePage } from "@/pages/TimelinePage";
import { DiagnosisPage } from "@/pages/DiagnosisPage";
import { NotFoundPage } from "@/pages/NotFoundPage";

export const router = createBrowserRouter([
  {
    element: <AppLayout />,
    children: [
      { path: "/", element: <HomePage /> },
    ],
  },
  {
    element: <AppLayout showSideNav />,
    children: [
      { path: "/novels/:novelId", element: <NovelDetailPage /> },
      { path: "/novels/:novelId/curves", element: <CurvesPage /> },
      { path: "/novels/:novelId/characters", element: <CharactersPage /> },
      { path: "/novels/:novelId/graph", element: <GraphPage /> },
      { path: "/novels/:novelId/topics", element: <TopicsPage /> },
      { path: "/novels/:novelId/timeline", element: <TimelinePage /> },
      { path: "/novels/:novelId/diagnosis", element: <DiagnosisPage /> },
    ],
  },
  { path: "*", element: <NotFoundPage /> },
]);
