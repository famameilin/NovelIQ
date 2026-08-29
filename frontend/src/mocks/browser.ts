/**
 * MSW Browser Setup — 开发环境启动 Mock Service Worker
 *
 * 启动方式：在 main.tsx 中条件引入此文件
 * 默认仅在 VITE_ENABLE_MOCK=true 时激活
 */
import { setupWorker } from "msw/browser";
import {
  novelListHandler,
  novelDetailHandler,
  novelCoverHandler,
  novelUploadHandler,
  novelDeleteHandler,
  novelBatchDeleteHandler,
} from "./handlers/novels";
import {
  createTaskHandler,
  reanalyzeHandler,
  taskStatusHandler,
  resumeTaskHandler,
  analysisTasksHandler,
  deleteTaskHandler,
  batchDeleteTasksHandler,
  cancelTaskHandler,
} from "./handlers/analysis";
import {
  charactersHandler,
  emotionTrendHandler,
  diagnosisHandler,
  foreshadowingThreadsHandler,
  graphChangesHandler,
  timelineHandler,
  topicSeriesHandler,
  topicShiftsHandler,
  topicEmotionHandler,
} from "./handlers/results";
import { linguisticFeaturesHandler, linguisticWord2vecHandler } from "./handlers/linguistic";
import {
  characterFunctionTabHandler,
  dashboardTabHandler,
  graphNetworkTabHandler,
  linguisticEntitiesTabHandler,
  rhythmTabHandler,
  topicsOverviewTabHandler,
} from "./handlers/tabs";

export const worker = setupWorker(
  // 小说
  novelListHandler,
  novelDetailHandler,
  novelCoverHandler,
  novelUploadHandler,
  novelDeleteHandler,
  novelBatchDeleteHandler,
  // 分析
  createTaskHandler,
  reanalyzeHandler,
  taskStatusHandler,
  resumeTaskHandler,
  analysisTasksHandler,
  deleteTaskHandler,
  batchDeleteTasksHandler,
  cancelTaskHandler,
  // 结果（单源 tab 数据源）
  charactersHandler,
  emotionTrendHandler,
  diagnosisHandler,
  foreshadowingThreadsHandler,
  graphChangesHandler,
  timelineHandler,
  topicSeriesHandler,
  topicShiftsHandler,
  topicEmotionHandler,
  linguisticFeaturesHandler,
  linguisticWord2vecHandler,
  // Tab 级聚合
  dashboardTabHandler,
  rhythmTabHandler,
  characterFunctionTabHandler,
  graphNetworkTabHandler,
  topicsOverviewTabHandler,
  linguisticEntitiesTabHandler,
);
