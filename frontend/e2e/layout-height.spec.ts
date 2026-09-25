import { expect, test, type Page, type Route } from '@playwright/test';

import {
  createChapterMetrics,
  createCharacterStats,
  createCharacters,
  createDiagnosis,
  createEmotionStats,
  createEmotionTrendWindows,
  createEventTimeline,
  createForeshadowingThreads,
  createGraph,
  createGraphChangesPage,
  createNarrativeStructure,
  createParagraphCurves,
  createStyleStats,
  createTopics,
} from '../src/mocks/data';

const NOVEL_ID = 'layout01';
const TASK_ID = 'layout-task';
const DESKTOP_SCREEN = { width: 1920, height: 1080 } as const;
const DESKTOP_VIEWPORT = { width: 1920, height: 943 } as const;

interface PageViewCase {
  label: string;
  role: 'button' | 'tab';
  expectInternalScroll?: boolean;
  revealMore?: boolean;
}

interface PageHeightCase {
  label: string;
  pathSuffix: string;
  views?: readonly PageViewCase[];
}

interface HeightMeasurement {
  page: string;
  view: string;
  path: string;
  viewportHeight: number;
  clientHeight: number;
  scrollHeight: number;
  overflow: number;
  internalScrollCount: number;
}

const PAGE_HEIGHT_CASES: readonly PageHeightCase[] = [
  { label: '仪表盘', pathSuffix: '' },
  {
    label: '情绪/节奏曲线',
    pathSuffix: '/curves',
    views: [
      { label: '情绪趋势', role: 'tab' },
      { label: '节奏张力', role: 'tab' },
    ],
  },
  {
    label: '角色分析',
    pathSuffix: '/characters',
    views: [
      { label: '格局概览', role: 'tab' },
      { label: '角色排行', role: 'tab', expectInternalScroll: true },
      { label: '角色详情', role: 'tab' },
    ],
  },
  {
    label: '人物关系图谱',
    pathSuffix: '/graph',
    views: [
      { label: '人物关系', role: 'tab' },
      { label: '关系演变', role: 'tab', revealMore: true },
    ],
  },
  {
    label: '主题分布',
    pathSuffix: '/topics',
    views: [
      { label: '主题总览', role: 'tab' },
      { label: '完整主题分布', role: 'tab', expectInternalScroll: true },
      { label: '主题演进', role: 'tab' },
      { label: '主题迁移', role: 'tab' },
      { label: '主题情绪', role: 'tab' },
    ],
  },
  {
    label: '语言特征',
    pathSuffix: '/linguistic',
    views: [
      { label: '表达结构', role: 'tab' },
      { label: '实体与短语', role: 'tab' },
      { label: '词汇与语义', role: 'tab' },
    ],
  },
  {
    label: '叙事时间轴',
    pathSuffix: '/timeline',
    views: [
      { label: '事件轨道', role: 'tab' },
      { label: '事件详情', role: 'tab' },
    ],
  },
  {
    label: '诊断报告',
    pathSuffix: '/diagnosis',
    views: [
      { label: '综合概览', role: 'tab' },
      { label: '价值主题', role: 'tab', expectInternalScroll: true },
      { label: '角色结构', role: 'tab', expectInternalScroll: true },
      { label: '伏笔追踪', role: 'tab', expectInternalScroll: true },
    ],
  },
];

/**
 * 2026-08-31 作用：组装页面高度测试使用的当前接口响应
 * 简要说明：复用项目数据工厂并补齐各页面所需的聚合合同
 */
function createMockApiResponses(): Readonly<Record<string, unknown>> {
  const characterTemplates = createCharacters(10);
  // 2026-08-31 作用：以真实任务量级覆盖角色长列表
  // 简要说明：重复角色画像字段但保持名称唯一以验证页签内部滚动
  const characters = Array.from({ length: 20 }, (_, index) => {
    const template = characterTemplates[index % characterTemplates.length];
    return {
      ...template,
      name: index < characterTemplates.length ? template.name : `${template.name}${index + 1}`,
      appearance_count: template.appearance_count + index,
    };
  });
  const diagnosis = {
    ...createDiagnosis(),
    value_logic_reason: Array.from(
      { length: 18 },
      (_, index) => `第 ${index + 1} 条价值判断说明用于验证长文本仍可完整滚动查看`,
    ).join('；'),
    focus_characters: Array.from({ length: 40 }, (_, index) => `焦点角色长名称${index + 1}`),
    core_cast: Array.from({ length: 80 }, (_, index) => `核心角色长名称${index + 1}`),
    main_characters: Array.from({ length: 100 }, (_, index) => `主要角色长名称${index + 1}`),
  };
  const emotionTrend = createEmotionTrendWindows(20, null);
  const graph = createGraph();
  const graphChangeTemplates = createGraphChangesPage(null, 8).changes;
  // 2026-08-31 作用：构造可在本地继续展开的图谱变化列表
  // 简要说明：验证初始八条记录展开后仍只在页签内部滚动
  const graphChanges = {
    changes: Array.from({ length: 40 }, (_, index) => {
      const template = graphChangeTemplates[index % graphChangeTemplates.length];
      return {
        ...template,
        change_id: `layout-change-${index + 1}`,
        fact_id: `layout-fact-${index + 1}`,
        effective_chapter_id: index + 1,
      };
    }),
    page_info: {
      limit: 200,
      returned_count: 40,
      total: 40,
      has_more: false,
      next_cursor: null,
    },
  };
  // 2026-08-31 作用：构造高主题数量且键值唯一的压力数据
  // 简要说明：避免重复词键告警干扰页面运行时错误门禁
  const topics = createTopics(25).map((topic, topicIndex) => ({
    ...topic,
    words: topic.words.map((word) => `${word}${topicIndex + 1}`),
  }));
  const foreshadowingTemplate = createForeshadowingThreads()[0];
  // 2026-08-31 作用：覆盖伏笔追踪长列表的页面高度边界
  // 简要说明：使用多条不同章节线索验证记录只在页签内部滚动
  const foreshadowingThreads = Array.from({ length: 8 }, (_, index) => ({
    ...foreshadowingTemplate,
    setup_id: `setup-layout-${index + 1}`,
    first_chapter_id: index * 3 + 1,
    last_chapter_id: index * 3 + 8,
    anchor_chapter_ids: [index * 3 + 1, index * 3 + 4, index * 3 + 8],
    setup_summary: `第 ${index + 1} 条伏笔线索在多个章节持续出现并等待后续回收`,
  }));
  const topicWeightTotal = topics.reduce((total, topic) => total + topic.weight, 0);
  const topicDistribution = topics.map((topic) => ({
    topic_id: topic.topic_id,
    weight: topic.weight / topicWeightTotal,
  }));
  const topicModel = {
    model_key: 'gensim-lda',
    library_version: '4.4.0',
    pipeline_version: '1.0',
    num_topics: topics.length,
    artifact_key: 'models/topic/layout-test',
  };
  const timeline = createEventTimeline();
  timeline.meta.novel_id = NOVEL_ID;
  timeline.meta.novel_name = '布局校验小说';

  const linguisticGroup = {
    token_total: 72000,
    sentence_total: 4800,
    word_length_ratios: { 1: 0.18, 2: 0.46, 3: 0.19, 4: 0.12, '5_plus': 0.05 },
    pos_ratios: { noun: 0.32, verb: 0.21, adj: 0.12, adv: 0.08, other: 0.27 },
    sentence_pattern_ratios: { short: 0.42, medium: 0.31, long: 0.18, compound: 0.09 },
    avg_dependency_depth: 2.84,
    max_dependency_depth: 9,
    dependency_relation_ratios: { HED: 0.18, SBV: 0.24, VOB: 0.22, ATT: 0.21, other: 0.15 },
    dependency_root_count: 4800,
  };
  const centroids = [
    { pos_group: 'noun', weighted_token_total: 7680, embedding_vector: [1, 0] },
    { pos_group: 'verb', weighted_token_total: 5040, embedding_vector: [0, 1] },
    { pos_group: 'adj', weighted_token_total: 2880, embedding_vector: [0.7071, 0.7071] },
  ];

  return {
    '/api/novels': {
      items: [],
      total: 0,
      page: 1,
      page_size: 12,
      total_pages: 0,
    },
    '/api/novels/': {
      items: [],
      total: 0,
      page: 1,
      page_size: 12,
      total_pages: 0,
    },
    [`/api/novels/${NOVEL_ID}`]: {
      novel_id: NOVEL_ID,
      title: '布局校验小说',
      filename: '布局校验小说.txt',
      author: '测试作者',
      upload_time: '2026-08-31T10:00:00Z',
      file_size: 128000,
    },
    [`/api/novels/${NOVEL_ID}/tasks`]: {
      novel_id: NOVEL_ID,
      tasks: [
        {
          task_id: TASK_ID,
          novel_id: NOVEL_ID,
          status: 'completed',
          created_at: '2026-08-31T10:00:00Z',
        },
      ],
    },
    [`/api/novels/${NOVEL_ID}/tasks/${TASK_ID}/status`]: {
      novel_id: NOVEL_ID,
      task_id: TASK_ID,
      status: 'completed',
      progress: 100,
      current_step: 'completed',
      stage: 'completed',
      message: '分析完成',
    },
    [`/api/novels/${NOVEL_ID}/tabs/dashboard`]: {
      run_id: TASK_ID,
      narrative_structure: createNarrativeStructure(),
      emotion_stats: createEmotionStats(),
      character_stats: createCharacterStats(),
      style_stats: createStyleStats(),
      chapter_metrics: createChapterMetrics(),
      topics,
      diagnosis,
      emotion_trend: emotionTrend,
    },
    [`/api/novels/${NOVEL_ID}/emotion-trend`]: emotionTrend,
    [`/api/novels/${NOVEL_ID}/tabs/rhythm`]: {
      run_id: TASK_ID,
      curves: createParagraphCurves(80),
      narrative_structure: createNarrativeStructure(),
    },
    [`/api/novels/${NOVEL_ID}/characters`]: characters,
    [`/api/novels/${NOVEL_ID}/tabs/character-function`]: {
      run_id: TASK_ID,
      characters,
      focus_structure: diagnosis.focus_structure ?? null,
      focus_characters: diagnosis.focus_characters ?? null,
      arc_scores: diagnosis.arc_scores ?? null,
    },
    [`/api/novels/${NOVEL_ID}/tabs/graph-network`]: {
      run_id: TASK_ID,
      snapshot: graph,
      character_appearances: characters.map((character) => ({
        name: character.name,
        appearance_count: character.appearance_count,
      })),
      graph_metrics: {
        run_id: TASK_ID,
        unavailable_reason: null,
        algorithm: { version: 'graph-metrics-v1' },
        pagerank: Object.fromEntries(graph.nodes.map((node, index) => [node.name, 1 / (index + 2)])),
        hits: { authority: {}, hub: {} },
        communities: { community_ids: {}, modularity: 0.42 },
      },
      change_total: graphChanges.page_info.total,
      unavailable_reason: null,
    },
    [`/api/novels/${NOVEL_ID}/graph/changes`]: graphChanges,
    [`/api/novels/${NOVEL_ID}/tabs/topics-overview`]: {
      run_id: TASK_ID,
      model: topicModel,
      topics,
      distribution: topicDistribution,
      chapters: [1, 2, 3].map((chapterId) => ({
        chapter_id: chapterId,
        chapter_sequence: chapterId,
        chapter_title: `第 ${chapterId} 章`,
        token_total: 1200,
        distribution: topicDistribution,
      })),
      keywords: topics.flatMap((topic) => topic.words.slice(0, 2)).map((word, index) => ({
        word,
        score: 1 / (index + 2),
      })),
      topic_labels: topics.map((topic, index) => topic.label ?? `主题 ${index + 1}`),
      unavailable_reason: null,
      keyword_unavailable_reason: null,
    },
    [`/api/novels/${NOVEL_ID}/topics/series`]: {
      run_id: TASK_ID,
      model: topicModel,
      num_topics: topics.length,
      points: Array.from({ length: 12 }, (_, index) => ({
        paragraph_id: index + 1,
        chapter_id: Math.floor(index / 3) + 1,
        chapter_sequence: Math.floor(index / 3) + 1,
        start_position: index * 960,
        token_count: 240,
        weights: topicDistribution.map((entry) => entry.weight),
      })),
      unavailable_reason: null,
    },
    [`/api/novels/${NOVEL_ID}/topics/shifts`]: {
      candidates: [
        { position: 2880, paragraph_start: 3, paragraph_end: 5, score: 0.48, window_token_total: 1440 },
      ],
      config: { window_size: 6, min_tokens_per_window: 800, score_threshold: 0.3, max_candidates: 20 },
      unavailable_reason: null,
    },
    [`/api/novels/${NOVEL_ID}/topics/emotion`]: {
      run_id: TASK_ID,
      model: topicModel,
      emotion: topics.map((topic, index) => ({
        topic_id: topic.topic_id,
        emotion: index % 2 === 0 ? 0.21 : -0.14,
        weighted_token_total: 9000 - index * 700,
      })),
      unavailable_reason: null,
    },
    [`/api/novels/${NOVEL_ID}/linguistic/features`]: {
      run_id: TASK_ID,
      paragraph_count: 420,
      ...linguisticGroup,
      chapters: [],
      unavailable_reason: null,
    },
    [`/api/novels/${NOVEL_ID}/tabs/linguistic-entities`]: {
      run_id: TASK_ID,
      count_by_type: { person: 186, location: 74, organization: 31, item: 22 },
      surface_top: Array.from({ length: 20 }, (_, index) => ({
        surface_text: `高频实体${index + 1}`,
        entity_type: index % 3 === 0 ? 'location' : 'person',
        count: 100 - index * 3,
      })),
      total_char_count: 186000,
      metric_hit_count: 0,
      fixed_phrase_density: 0,
      four_char_candidate_count: 12,
      total_hits: 59,
      unavailable_reason: null,
    },
    [`/api/novels/${NOVEL_ID}/linguistic/word2vec`]: {
      run_id: TASK_ID,
      model: { embedding_dimension: 2, vocabulary_size: 48210, artifact_scope: 'pretrained_finetuned' },
      pos_coverage: [
        { pos_group: 'noun', source_token_total: 7680, in_vocabulary_token_total: 7104, coverage_ratio: 0.925 },
        { pos_group: 'verb', source_token_total: 5040, in_vocabulary_token_total: 4420, coverage_ratio: 0.8769 },
        { pos_group: 'adj', source_token_total: 2880, in_vocabulary_token_total: 2210, coverage_ratio: 0.7674 },
      ],
      pos_centroids: centroids,
      pos_similarity_matrix: [
        [1, 0, 0.7071],
        [0, 1, 0.7071],
        [0.7071, 0.7071, 1],
      ],
      unavailable_reason: null,
    },
    [`/api/novels/${NOVEL_ID}/timeline`]: timeline,
    [`/api/novels/${NOVEL_ID}/diagnosis`]: diagnosis,
    [`/api/novels/${NOVEL_ID}/foreshadowing-threads`]: foreshadowingThreads,
  };
}

/**
 * 2026-08-31 作用：安装页面高度测试所需的即时接口响应
 * 简要说明：未知接口返回明确错误并记录请求路径
 */
async function installAnalysisApiMocks(page: Page): Promise<Set<string>> {
  const responses = createMockApiResponses();
  const unhandledRequests = new Set<string>();

  /**
   * 2026-08-31 作用：响应页面测试期间发出的接口请求
   * 简要说明：事件流进入完成态其余请求按当前路径合同返回
   */
  const handleRoute = async (route: Route) => {
    const request = route.request();
    const requestUrl = new URL(request.url());
    const pathname = requestUrl.pathname;

    if (request.method() === 'GET' && pathname === `/api/novels/${NOVEL_ID}/events/tasks/${TASK_ID}`) {
      await route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        headers: { 'cache-control': 'no-cache' },
        body: 'retry: 60000\nid: 1\nevent: task_complete\ndata: {}\n\n',
      });
      return;
    }

    const response = responses[pathname];
    if (request.method() !== 'GET' || response === undefined) {
      unhandledRequests.add(`${request.method()} ${requestUrl.pathname}${requestUrl.search}`);
      await route.fulfill({
        status: 501,
        contentType: 'application/json',
        body: JSON.stringify({ detail: `页面高度测试缺少接口响应 ${request.method()} ${pathname}` }),
      });
      return;
    }

    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(response),
    });
  };

  await page.route(/^https?:\/\/[^/]+\/api\/.*/, handleRoute);
  return unhandledRequests;
}

/**
 * 2026-08-31 作用：等待页面主体和字体完成首轮布局
 * 简要说明：排除懒加载骨架和字体切换造成的瞬时尺寸
 */
async function waitForStableLayout(
  page: Page,
  pageLabel: string,
  runtimeErrors: readonly string[],
): Promise<void> {
  const main = page.locator('main');
  await expect(
    main,
    `${pageLabel} 未进入可测量页面状态\n${runtimeErrors.join('\n')}`,
  ).toBeVisible({ timeout: 10_000 });
  await page.waitForFunction(() => {
    const pageMain = document.querySelector('main');
    return pageMain != null && pageMain.querySelector('.animate-pulse') == null;
  });
  await page.evaluate(async () => {
    await document.fonts.ready;
  });
  await main.evaluate((mainElement) => {
    delete mainElement.dataset.layoutHeightSignature;
    delete mainElement.dataset.layoutHeightStableSince;
  });
  await page.waitForFunction(() => {
    const pageMain = document.querySelector('main');
    const scrollContainer = pageMain?.parentElement;
    if (!(pageMain instanceof HTMLElement) || !(scrollContainer instanceof HTMLElement)) {
      return false;
    }

    const signature = [
      scrollContainer.clientWidth,
      scrollContainer.scrollWidth,
      scrollContainer.clientHeight,
      scrollContainer.scrollHeight,
    ].join(':');
    if (pageMain.dataset.layoutHeightSignature !== signature) {
      pageMain.dataset.layoutHeightSignature = signature;
      pageMain.dataset.layoutHeightStableSince = String(performance.now());
      return false;
    }

    const stableSince = Number(pageMain.dataset.layoutHeightStableSince);
    return Number.isFinite(stableSince) && performance.now() - stableSince >= 350;
  });
}

/**
 * 2026-08-31 作用：测量业务页面主内容区的竖向溢出
 * 简要说明：以 main 的直接滚动父容器作为统一页面高度边界
 */
async function measurePageHeight(page: Page, pageCase: PageHeightCase, view: string): Promise<HeightMeasurement> {
  const measurement = await page.locator('main').evaluate((mainElement) => {
    const scrollContainer = mainElement.parentElement;
    if (!(scrollContainer instanceof HTMLElement)) {
      throw new Error('页面 main 缺少主滚动容器');
    }

    return {
      viewportHeight: window.innerHeight,
      clientHeight: scrollContainer.clientHeight,
      scrollHeight: scrollContainer.scrollHeight,
      internalScrollCount: [...mainElement.querySelectorAll('*')].filter((element) => {
        if (!(element instanceof HTMLElement)) return false;
        const overflowY = getComputedStyle(element).overflowY;
        return (overflowY === 'auto' || overflowY === 'scroll') && element.scrollHeight > element.clientHeight;
      }).length,
    };
  });
  const url = new URL(page.url());

  return {
    page: pageCase.label,
    view,
    path: `${url.pathname}${url.search}`,
    ...measurement,
    overflow: measurement.scrollHeight - measurement.clientHeight,
  };
}

/**
 * 2026-08-31 作用：格式化页面高度门禁的失败信息
 * 简要说明：逐项报告路由视图和超过可用高度的像素数
 */
function formatOverflowReport(measurements: readonly HeightMeasurement[]): string {
  return measurements
    .map(
      (item) =>
        `${item.page} / ${item.view} ${item.path} ` +
        `视口高度=${item.viewportHeight}px 可用高度=${item.clientHeight}px ` +
        `内容高度=${item.scrollHeight}px 超出=${item.overflow}px`,
    )
    .join('\n');
}

test.describe('全局页面高度门禁', () => {
  test.use({ viewport: DESKTOP_VIEWPORT, screen: DESKTOP_SCREEN });

  /**
   * 2026-08-31 作用：验证全部业务页面不会撑出页面级竖向滚动
   * 简要说明：覆盖侧栏路由及其页面主体切换状态
   */
  test('所有业务页面内容必须处于 1920x1080 最大化桌面网页可用高度内', async ({ page }) => {
    test.setTimeout(30_000);
    expect(page.viewportSize(), '页面高度门禁必须使用 1920x1080 屏幕的最大化 Chromium 实测视口').toEqual(
      DESKTOP_VIEWPORT,
    );
    const unhandledRequests = await installAnalysisApiMocks(page);
    const measurements: HeightMeasurement[] = [];
    const runtimeErrors: string[] = [];
    page.on('pageerror', (error) => runtimeErrors.push(`PAGEERROR ${error.message}`));
    page.on('console', (message) => {
      if (message.type() === 'error') runtimeErrors.push(`CONSOLE ${message.text()}`);
    });
    page.on('requestfailed', (request) => {
      runtimeErrors.push(`REQUEST ${request.method()} ${request.url()} ${request.failure()?.errorText ?? '未知错误'}`);
    });

    for (const pageCase of PAGE_HEIGHT_CASES) {
      const path = `/novels/${NOVEL_ID}${pageCase.pathSuffix}?task_id=${TASK_ID}`;
      await page.goto(path);
      await waitForStableLayout(page, `${pageCase.label} ${path}`, runtimeErrors);

      if (!pageCase.views) {
        measurements.push(await measurePageHeight(page, pageCase, '默认视图'));
        continue;
      }

      for (const view of pageCase.views) {
        const control = page.getByRole(view.role, { name: view.label, exact: true });
        await expect(control).toBeVisible();
        if ((await control.getAttribute('aria-selected')) !== 'true') {
          await control.click();
          await waitForStableLayout(page, `${pageCase.label} / ${view.label} ${path}`, runtimeErrors);
        }
        const measurement = await measurePageHeight(page, pageCase, view.label);
        measurements.push(measurement);
        if (view.expectInternalScroll) {
          expect(
            measurement.internalScrollCount,
            `${pageCase.label} / ${view.label} 的长内容缺少页签内部滚动区`,
          ).toBeGreaterThan(0);
        }
        if (view.revealMore) {
          const revealMore = page.getByRole('button', { name: '显示更多', exact: true });
          await expect(revealMore).toBeVisible();
          await revealMore.click();
          await waitForStableLayout(page, `${pageCase.label} / ${view.label}展开后 ${path}`, runtimeErrors);
          const expandedMeasurement = await measurePageHeight(page, pageCase, `${view.label}展开后`);
          measurements.push(expandedMeasurement);
          expect(
            expandedMeasurement.internalScrollCount,
            `${pageCase.label} / ${view.label} 展开后缺少页签内部滚动区`,
          ).toBeGreaterThan(0);
        }
      }
    }

    expect(
      [...unhandledRequests],
      `页面高度测试存在未登记的接口请求\n${[...unhandledRequests].join('\n')}`,
    ).toEqual([]);
    expect(
      runtimeErrors,
      `页面高度测试存在运行时错误\n${runtimeErrors.join('\n')}`,
    ).toEqual([]);

    const overflowingPages = measurements.filter((measurement) => measurement.overflow > 0);
    expect(
      overflowingPages,
      `检测到页面内容高度超过 1920x1080 最大化桌面网页可用高度\n${formatOverflowReport(overflowingPages)}`,
    ).toEqual([]);
  });
});
