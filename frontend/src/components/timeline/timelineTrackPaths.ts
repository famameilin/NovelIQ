// 2026-04-23，任务：复杂度与耦合审查 P1
// 把 TimelineTrack 的 SVG path 生成与张力插值抽成纯函数，便于单独测试

export interface TimelineTensionPath {
  linePath: string;
  areaPath: string;
}

export const TRACK_CURVE_START_PADDING_PX = 28;
export const TRACK_CURVE_END_PADDING_PX = 68;
export const TRACK_HEIGHT_PX = 430;
export const CURVE_CENTER_Y = 202;
export const CURVE_AMPLITUDE_PX = 60;

export function getNormalizedProgress(progress: number): number {
  return Math.min(Math.max(progress, 0), 1);
}

export function getTrackPositionPx(
  progress: number,
  canvasWidth: number,
  startPaddingPx: number,
  endPaddingPx: number
): number {
  const normalized = getNormalizedProgress(progress);
  return startPaddingPx + normalized * Math.max(canvasWidth - startPaddingPx - endPaddingPx, 0);
}

export function normalizeSeriesValue(value: number, series: number[]): number {
  const min = Math.min(...series);
  const max = Math.max(...series);
  if (max - min < 1e-6) {
    return 0.5;
  }
  return (value - min) / (max - min);
}

export function mapTensionValueToTrackY(value: number, series: number[]): number {
  const normalized = normalizeSeriesValue(value, series);
  return CURVE_CENTER_Y + (0.5 - normalized) * CURVE_AMPLITUDE_PX * 2;
}

export function interpolateSeriesValueAtProgress(progress: number, series: number[], totalChunks: number): number {
  if (series.length === 0) {
    return 0;
  }
  if (series.length === 1) {
    return series[0] ?? 0;
  }

  const normalized = getNormalizedProgress(progress);
  const maxIndex = totalChunks > 1 ? totalChunks - 1 : series.length - 1;
  const sampleIndex = normalized * Math.max(maxIndex, 1);
  const leftIndex = Math.max(0, Math.min(Math.floor(sampleIndex), series.length - 1));
  const rightIndex = Math.max(0, Math.min(Math.ceil(sampleIndex), series.length - 1));

  if (leftIndex === rightIndex) {
    return series[leftIndex] ?? 0;
  }

  const leftValue = series[leftIndex] ?? 0;
  const rightValue = series[rightIndex] ?? leftValue;
  const ratio = sampleIndex - leftIndex;
  return leftValue + (rightValue - leftValue) * ratio;
}

export function getCurveNodeYPx(progress: number, tensionCurve: number[], totalChunks: number): number {
  if (tensionCurve.length === 0) {
    return CURVE_CENTER_Y;
  }

  const interpolatedValue = interpolateSeriesValueAtProgress(progress, tensionCurve, totalChunks);
  return mapTensionValueToTrackY(interpolatedValue, tensionCurve);
}

export function buildTensionAreaPath(
  tensionCurve: number[],
  totalChunks: number,
  canvasWidth: number
): TimelineTensionPath | null {
  const normalizedPoints = tensionCurve.map((value, index) => {
    const xProgress = totalChunks > 1 ? index / Math.max(totalChunks - 1, 1) : index / Math.max(tensionCurve.length - 1, 1);
    const clampedValue = Number.isFinite(value) ? value : 0;
    return {
      x: getTrackPositionPx(xProgress, canvasWidth, TRACK_CURVE_START_PADDING_PX, TRACK_CURVE_END_PADDING_PX),
      y: mapTensionValueToTrackY(clampedValue, tensionCurve),
    };
  });

  if (normalizedPoints.length === 0) {
    return null;
  }

  const linePath = normalizedPoints
    .map((point, index) => `${index === 0 ? "M" : "L"} ${point.x.toFixed(2)} ${point.y.toFixed(2)}`)
    .join(" ");
  const areaFloor = TRACK_HEIGHT_PX;
  const areaPath = `${linePath} L ${normalizedPoints[normalizedPoints.length - 1]?.x.toFixed(2)} ${areaFloor} L ${normalizedPoints[0]?.x.toFixed(2)} ${areaFloor} Z`;

  return { linePath, areaPath };
}
