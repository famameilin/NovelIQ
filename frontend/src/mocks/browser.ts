/**
 * MSW Browser Setup — 开发环境启动 Mock Service Worker
 *
 * 启动方式：在 main.tsx 中条件引入此文件
 * 默认仅在 VITE_ENABLE_MOCK=true 时激活
 */
import { setupWorker } from "msw/browser";
import { novelListHandler, novelUploadHandler, novelDeleteHandler, novelBatchDeleteHandler } from "./handlers/novels";
import {
  createTaskHandler,
  analyzeHandler,
  reanalyzeHandler,
  taskStatusHandler,
  analysisStatusHandler,
  resumeTaskHandler,
  analysisTasksHandler,
  deleteTaskHandler,
  batchDeleteTasksHandler,
  cancelTaskHandler,
} from "./handlers/analysis";
import {
  charactersHandler,
  paragraphCurvesHandler,
  emotionTrendHandler,
  chapterMetricsHandler,
  topicsHandler,
  diagnosisHandler,
  foreshadowingThreadsHandler,
  graphHandler,
  graphChangesHandler,
  timelineHandler,
  narrativeStructureHandler,
  emotionStatsHandler,
  characterStatsHandler,
  styleStatsHandler,
} from "./handlers/results";

export const worker = setupWorker(
  // 小说
  novelListHandler,
  novelUploadHandler,
  novelDeleteHandler,
  novelBatchDeleteHandler,
  // 分析
  createTaskHandler,
  analyzeHandler,
  reanalyzeHandler,
  taskStatusHandler,
  analysisStatusHandler,
  resumeTaskHandler,
  analysisTasksHandler,
  deleteTaskHandler,
  batchDeleteTasksHandler,
  cancelTaskHandler,
  // 结果
  charactersHandler,
  paragraphCurvesHandler,
  emotionTrendHandler,
  chapterMetricsHandler,
  topicsHandler,
  diagnosisHandler,
  foreshadowingThreadsHandler,
  graphHandler,
  graphChangesHandler,
  timelineHandler,
  narrativeStructureHandler,
  emotionStatsHandler,
  characterStatsHandler,
  styleStatsHandler,
);
