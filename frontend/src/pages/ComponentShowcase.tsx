import { useEffect, useState, useMemo } from "react";
import { toast } from "sonner";
import { PageContainer } from "@/components/layout/PageContainer";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
  CardFooter,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogTrigger,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
  DialogClose,
} from "@/components/ui/dialog";
import {
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectItem,
} from "@/components/ui/select";
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
} from "@/components/ui/table";
import {
  Tooltip,
  TooltipTrigger,
  TooltipContent,
} from "@/components/ui/tooltip";
import { Separator } from "@/components/ui/separator";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuLabel,
} from "@/components/ui/dropdown-menu";
import { MetricCard } from "@/components/common/MetricCard";
import { SegmentedBar } from "@/components/common/SegmentedBar";
import { AnalysisProgressRing } from "@/components/common/AnalysisProgressRing";
import { useThemeStore } from "@/store/themeStore";
import {
  Zap,
  Heart,
  Users,
  Palette,
  BookOpen,
  MoreVertical,
  TrendingUp,
  BarChart3,
  Activity,
} from "lucide-react";

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="space-y-4">
      <h2 className="text-xl font-semibold text-text">{title}</h2>
      <Separator />
      {children}
    </section>
  );
}

const MONITOR_VARS = [
  "--primary",
  "--background",
  "--surface",
  "--border",
  "--text",
  "--chart-1",
  "--chart-2",
  "--chart-3",
];

function LiveCSSMonitor() {
  const vars = useMemo(() => {
    const root = document.documentElement;
    const values: Record<string, string> = {};
    for (const name of MONITOR_VARS) {
      values[name] = root.style.getPropertyValue(name) ||
        getComputedStyle(root).getPropertyValue(name).trim();
    }
    return values;
  }, []);

  return (
    <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
      {MONITOR_VARS.map((name) => (
        <div key={name} className="flex items-center gap-3 rounded-md border border-border px-3 py-2">
          <span
            className="h-8 w-8 shrink-0 rounded-md border border-border-subtle"
            style={{ backgroundColor: vars[name] ? `hsl(${vars[name]})` : "transparent" }}
          />
          <div className="min-w-0">
            <div className="truncate text-xs font-mono text-text-muted">{name}</div>
            <div className="truncate text-xs font-mono font-semibold text-text">
              {vars[name] || "–"}
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

export function ComponentShowcase() {
  const { seedColor, setSeedColor, setAutoSyncEnabled } = useThemeStore();
  const [progress, setProgress] = useState(66);

  // 中文注释：组件展示页允许手动试色，挂载期间临时关闭“按任务自动回填主题色”。
  useEffect(() => {
    setAutoSyncEnabled(false);
    return () => {
      setAutoSyncEnabled(true);
    };
  }, [setAutoSyncEnabled]);

  const presetColors = [
    { label: "默认 Indigo", hex: "#6366F1" },
    { label: "仙侠 紫", hex: "#6C5CE7" },
    { label: "都市 青", hex: "#4A9E9E" },
    { label: "玄幻 金", hex: "#D4A843" },
    { label: "悬疑 红", hex: "#C0392B" },
    { label: "言情 粉", hex: "#E84393" },
    { label: "科幻 蓝", hex: "#00B4D8" },
  ];

  return (
    <PageContainer className="space-y-10 pb-20">
      <div>
        <h1 className="text-3xl font-bold text-text">组件展示</h1>
        <p className="mt-1 text-text-muted">
          Sprint 1-A 产出的全部 UI 组件与业务组件一览
        </p>
      </div>

      {/* ===== Theme Color Switcher ===== */}
      <Section title="动态主题色切换">
        <p className="text-sm text-text-secondary">
          点击下方色块可实时切换主题色，观察全页面颜色联动效果。当前种子色：
          <code className="ml-1 rounded bg-primary-subtle px-1.5 py-0.5 text-xs font-mono text-primary">
            {seedColor}
          </code>
        </p>
        <div className="flex flex-wrap gap-3">
          {presetColors.map((c) => (
            <button
              key={c.hex}
              onClick={() => setSeedColor(c.hex)}
              className="group flex items-center gap-2 rounded-lg border border-border px-3 py-2 text-sm transition-all hover:border-primary hover:shadow-sm"
            >
              <span
                className="inline-block h-5 w-5 rounded-full border border-border-subtle shadow-inner"
                style={{ backgroundColor: c.hex }}
              />
              <span className="text-text-secondary group-hover:text-text">
                {c.label}
              </span>
            </button>
          ))}
        </div>
      </Section>

      {/* ===== Live CSS Variable Monitor ===== */}
      <Section title="实时 CSS 变量监控">
        <p className="text-sm text-text-secondary">
          下表显示当前 <code>:root</code> 上的实际 CSS 变量值（切换主题色后实时变化）
        </p>
        <LiveCSSMonitor />
      </Section>

      {/* ===== MetricCard ===== */}
      <Section title="MetricCard 指标卡片">
        <p className="text-sm text-text-secondary mb-4">
          支持 <code className="rounded bg-primary-subtle px-1.5 py-0.5 text-xs font-mono text-primary">accent</code> 多色强调、
          <code className="rounded bg-primary-subtle px-1.5 py-0.5 text-xs font-mono text-primary">trend</code> 趋势标签、
          <code className="rounded bg-primary-subtle px-1.5 py-0.5 text-xs font-mono text-primary">showOrb</code> 装饰光斑、
          <code className="rounded bg-primary-subtle px-1.5 py-0.5 text-xs font-mono text-primary">footer</code> 自定义插槽。
        </p>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <MetricCard
            label="叙事结构"
            value={78}
            format="number"
            decimals={0}
            icon={<TrendingUp className="h-5 w-5" />}
            description="综合叙事结构评分，基于三幕比例、高潮间距、悬念率等指标计算"
            footer={
              <SegmentedBar
                segments={[
                  { label: "第一幕", value: 25, colorClass: "bg-chart-1" },
                  { label: "第二幕", value: 55, colorClass: "bg-chart-2" },
                  { label: "第三幕", value: 20, colorClass: "bg-chart-3" },
                ]}
              />
            }
          />
          <MetricCard
            label="伏笔回收预期"
            value={0.62}
            format="percent"
            icon={<Zap className="h-5 w-5" />}
            accent="chart-2"
            description="基于 Phase2 强 setup thread 状态估算的近似回收预期"
          />
          <MetricCard
            label="文化深度"
            value={3.8}
            format="score"
            maxScore={5}
            icon={<BookOpen className="h-5 w-5" />}
            accent="chart-4"
            showOrb
            description="综合成语密度、古典意象、文言比例的文化深度评分"
          />
          <MetricCard
            label="角色数量"
            value={42}
            format="number"
            decimals={0}
            icon={<Users className="h-5 w-5" />}
            accent="chart-3"
            trend="+12%"
            showOrb
            footer={
              <>
                <div className="flex -space-x-2">
                  {["李逍遥", "赵灵儿", "林月如", "阿奴"].map((name, i) => (
                    <div
                      key={name}
                      className="flex h-7 w-7 items-center justify-center rounded-full border-2 border-surface bg-gradient-to-br from-primary/20 to-primary/40 text-[10px] font-medium text-primary"
                      style={{ zIndex: 4 - i }}
                    >
                      {name[0]}
                    </div>
                  ))}
                </div>
                <span className="text-xs text-text-muted">+38 更多角色</span>
              </>
            }
          />
        </div>
      </Section>

      {/* ===== Buttons ===== */}
      <Section title="Button 按钮">
        <div className="flex flex-wrap items-center gap-3">
          <Button>默认按钮</Button>
          <Button variant="secondary">次要按钮</Button>
          <Button variant="outline">描边按钮</Button>
          <Button variant="ghost">幽灵按钮</Button>
          <Button variant="destructive">危险按钮</Button>
          <Button variant="link">链接按钮</Button>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <Button size="sm">小按钮</Button>
          <Button size="default">中按钮</Button>
          <Button size="lg">大按钮</Button>
          <Button size="icon">
            <Zap />
          </Button>
          <Button disabled>禁用</Button>
        </div>
      </Section>

      {/* ===== Badge ===== */}
      <Section title="Badge 标签">
        <div className="flex flex-wrap items-center gap-3">
          <Badge>默认</Badge>
          <Badge variant="secondary">次要</Badge>
          <Badge variant="outline">描边</Badge>
          <Badge variant="success">成功</Badge>
          <Badge variant="destructive">失败</Badge>
        </div>
      </Section>

      {/* ===== Card ===== */}
      <Section title="Card 卡片">
        <p className="text-sm text-text-secondary mb-4">
          支持 <code className="rounded bg-primary-subtle px-1.5 py-0.5 text-xs font-mono text-primary">default</code>（基础）和
          <code className="rounded bg-primary-subtle px-1.5 py-0.5 text-xs font-mono text-primary">elevated</code>（微渐变 + hover 抬升）两种 variant。悬浮卡片查看效果。
        </p>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Card>
            <CardHeader>
              <CardTitle>基础卡片</CardTitle>
              <CardDescription>这是一个基础卡片组件</CardDescription>
            </CardHeader>
            <CardContent>
              <p className="text-sm text-text-secondary">
                卡片内容区域，可放置任意子组件。
              </p>
            </CardContent>
            <CardFooter>
              <Button size="sm">操作</Button>
            </CardFooter>
          </Card>

          <Card className="border-primary/30 bg-primary-subtle/30">
            <CardHeader>
              <CardTitle>主题色卡片</CardTitle>
              <CardDescription>带主题色强调的卡片</CardDescription>
            </CardHeader>
            <CardContent>
              <p className="text-sm text-text-secondary">
                使用 primary-subtle 作为背景底色。
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>带操作的卡片</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              <div className="flex items-center gap-2">
                <Badge variant="success">已完成</Badge>
                <span className="text-sm text-text-secondary">分析任务 #1</span>
              </div>
            </CardContent>
            <CardFooter className="justify-between">
              <Button variant="outline" size="sm">查看详情</Button>
              <Button variant="ghost" size="sm">删除</Button>
            </CardFooter>
          </Card>

          <Card variant="elevated" className="bg-gradient-to-br from-surface via-surface to-chart-1/15">
            <CardHeader>
              <CardTitle>Elevated 卡片</CardTitle>
              <CardDescription>微渐变 + 悬停抬升</CardDescription>
            </CardHeader>
            <CardContent className="space-y-2">
              <div className="flex items-center gap-2">
                <Badge variant="success">已完成</Badge>
                <span className="text-sm text-text-secondary">分析任务 #1</span>
              </div>
            </CardContent>
            <CardFooter className="justify-between">
              <Button variant="outline" size="sm">查看详情</Button>
              <Button variant="ghost" size="sm">删除</Button>
            </CardFooter>
          </Card>
        </div>
      </Section>

      {/* ===== AnalysisProgressRing ===== */}
      <Section title="AnalysisProgressRing 进度环">
        <div className="flex flex-wrap items-end gap-6">
          <div className="flex flex-col items-center gap-2">
            <AnalysisProgressRing progress={0} size={48} />
            <span className="text-xs text-text-muted">0%</span>
          </div>
          <div className="flex flex-col items-center gap-2">
            <AnalysisProgressRing progress={25} size={48} />
            <span className="text-xs text-text-muted">25%</span>
          </div>
          <div className="flex flex-col items-center gap-2">
            <AnalysisProgressRing progress={50} size={56} strokeWidth={5} />
            <span className="text-xs text-text-muted">50%</span>
          </div>
          <div className="flex flex-col items-center gap-2">
            <AnalysisProgressRing progress={75} size={64} strokeWidth={5} />
            <span className="text-xs text-text-muted">75%</span>
          </div>
          <div className="flex flex-col items-center gap-2">
            <AnalysisProgressRing progress={100} size={72} strokeWidth={6} />
            <span className="text-xs text-text-muted">100%</span>
          </div>
          <div className="ml-4 flex flex-col gap-2">
            <span className="text-sm text-text-secondary">
              可交互：拖动滑块调整
            </span>
            <input
              type="range"
              min={0}
              max={100}
              value={progress}
              onChange={(e) => setProgress(Number(e.target.value))}
              className="w-40 accent-[hsl(var(--primary))]"
            />
            <AnalysisProgressRing progress={progress} size={80} strokeWidth={6} />
          </div>
        </div>
      </Section>

      {/* ===== Select ===== */}
      <Section title="Select 选择器">
        <div className="flex flex-wrap items-center gap-4">
          <Select>
            <SelectTrigger className="w-56">
              <SelectValue placeholder="选择分析任务" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="task-1">
                <span className="flex items-center gap-2">
                  <span className="font-mono text-xs">a1b2c3d4</span>
                  <Badge variant="success" className="text-[10px] px-1.5 py-0">
                    已完成
                  </Badge>
                </span>
              </SelectItem>
              <SelectItem value="task-2">
                <span className="flex items-center gap-2">
                  <span className="font-mono text-xs">e5f6g7h8</span>
                  <Badge variant="secondary" className="text-[10px] px-1.5 py-0">
                    分析中
                  </Badge>
                </span>
              </SelectItem>
              <SelectItem value="task-3">
                <span className="flex items-center gap-2">
                  <span className="font-mono text-xs">i9j0k1l2</span>
                  <Badge variant="destructive" className="text-[10px] px-1.5 py-0">
                    失败
                  </Badge>
                </span>
              </SelectItem>
            </SelectContent>
          </Select>
        </div>
      </Section>

      {/* ===== Dialog ===== */}
      <Section title="Dialog 对话框">
        <Dialog>
          <DialogTrigger asChild>
            <Button variant="outline">打开对话框</Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>确认删除</DialogTitle>
              <DialogDescription>
                确定要删除这本小说的所有分析数据吗？此操作不可撤销。
              </DialogDescription>
            </DialogHeader>
            <DialogFooter>
              <DialogClose asChild>
                <Button variant="outline">取消</Button>
              </DialogClose>
              <Button variant="destructive">确认删除</Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </Section>

      {/* ===== Tabs ===== */}
      <Section title="Tabs 标签页">
        <Tabs defaultValue="emotion" className="w-full max-w-lg">
          <TabsList>
            <TabsTrigger value="emotion">
              <Heart className="mr-1.5 h-3.5 w-3.5" />
              情感
            </TabsTrigger>
            <TabsTrigger value="rhythm">
              <Activity className="mr-1.5 h-3.5 w-3.5" />
              节奏
            </TabsTrigger>
            <TabsTrigger value="structure">
              <BarChart3 className="mr-1.5 h-3.5 w-3.5" />
              结构
            </TabsTrigger>
          </TabsList>
          <TabsContent value="emotion">
            <Card>
              <CardContent className="p-4 text-sm text-text-secondary">
                情感维度：正面密度 0.45 / 负面密度 0.32 / 净密度 0.13
              </CardContent>
            </Card>
          </TabsContent>
          <TabsContent value="rhythm">
            <Card>
              <CardContent className="p-4 text-sm text-text-secondary">
                节奏维度：张力峰值 0.87 / 高潮密度 3.2 / 回落速度 0.65
              </CardContent>
            </Card>
          </TabsContent>
          <TabsContent value="structure">
            <Card>
              <CardContent className="p-4 text-sm text-text-secondary">
                结构维度：三幕比例 25/55/20 / 中段塌陷指数 0.12
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>
      </Section>

      {/* ===== DropdownMenu ===== */}
      <Section title="DropdownMenu 下拉菜单">
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="outline" size="icon">
              <MoreVertical className="h-4 w-4" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent>
            <DropdownMenuLabel>操作</DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuItem>
              <Zap className="mr-2 h-4 w-4" />
              重新分析
            </DropdownMenuItem>
            <DropdownMenuItem>
              <Palette className="mr-2 h-4 w-4" />
              更换主题色
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem className="text-[hsl(var(--chart-negative))]">
              删除小说
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </Section>

      {/* ===== Table ===== */}
      <Section title="Table 表格">
        <Card>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>角色</TableHead>
                <TableHead>出场次数</TableHead>
                <TableHead>角色功能</TableHead>
                <TableHead className="text-right">主角分</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {[
                { name: "李逍遥", count: 342, role: "protagonist", score: 0.95 },
                { name: "赵灵儿", count: 287, role: "helper", score: 0.72 },
                { name: "林月如", count: 198, role: "helper", score: 0.58 },
                { name: "拜月教主", count: 76, role: "antagonist", score: 0.12 },
              ].map((char) => (
                <TableRow key={char.name}>
                  <TableCell className="font-medium">{char.name}</TableCell>
                  <TableCell>{char.count}</TableCell>
                  <TableCell>
                    <Badge
                      variant={
                        char.role === "protagonist"
                          ? "default"
                          : char.role === "antagonist"
                            ? "destructive"
                            : "secondary"
                      }
                    >
                      {char.role}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-right font-mono">
                    {char.score.toFixed(2)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Card>
      </Section>

      {/* ===== Tooltip ===== */}
      <Section title="Tooltip 提示">
        <div className="flex flex-wrap items-center gap-4">
          <Tooltip>
            <TooltipTrigger asChild>
              <Button variant="outline">悬浮查看提示</Button>
            </TooltipTrigger>
            <TooltipContent>
              <p>这是一个 Tooltip 提示内容</p>
            </TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger asChild>
              <Badge variant="secondary" className="cursor-help">
                伏笔兑现率 62%
              </Badge>
            </TooltipTrigger>
            <TooltipContent className="max-w-xs">
              <p>已兑现伏笔占已设置伏笔的比率，60% 以上表示作者有意识地管理伏笔线索。</p>
            </TooltipContent>
          </Tooltip>
        </div>
      </Section>

      {/* ===== Toast ===== */}
      <Section title="Toast 通知">
        <div className="flex flex-wrap items-center gap-3">
          <Button onClick={() => toast.success("分析完成！")}>成功通知</Button>
          <Button
            variant="destructive"
            onClick={() => toast.error("分析失败：模型超时")}
          >
            错误通知
          </Button>
          <Button
            variant="outline"
            onClick={() => toast.info("小说已上传，等待分析...")}
          >
            信息通知
          </Button>
          <Button
            variant="ghost"
            onClick={() =>
              toast("正在重新分析", {
                description: "预计需要 3-5 分钟",
                action: {
                  label: "取消",
                  onClick: () => toast.info("已取消"),
                },
              })
            }
          >
            带操作的通知
          </Button>
        </div>
      </Section>

      {/* ===== Color Palette Preview ===== */}
      <Section title="当前主题色板预览">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
          {[
            { name: "primary", class: "bg-primary text-text-on-primary" },
            { name: "primary-hover", class: "bg-primary-hover text-text-on-primary" },
            { name: "primary-active", class: "bg-primary-active text-text-on-primary" },
            { name: "primary-subtle", class: "bg-primary-subtle text-primary" },
            { name: "background", class: "bg-background text-text border border-border" },
            { name: "surface", class: "bg-surface text-text border border-border" },
            { name: "surface-hover", class: "bg-surface-hover text-text border border-border" },
            { name: "chart-1", class: "bg-chart-1 text-white" },
            { name: "chart-2", class: "bg-chart-2 text-white" },
            { name: "chart-3", class: "bg-chart-3 text-white" },
            { name: "chart-4", class: "bg-chart-4 text-white" },
            { name: "chart-5", class: "bg-chart-5 text-white" },
            { name: "chart-positive", class: "bg-chart-positive text-white" },
            { name: "chart-negative", class: "bg-chart-negative text-white" },
            { name: "chart-neutral", class: "bg-chart-neutral text-white" },
          ].map((swatch) => (
            <div
              key={swatch.name}
              className={`flex h-16 items-center justify-center rounded-md text-xs font-medium ${swatch.class}`}
            >
              {swatch.name}
            </div>
          ))}
        </div>
      </Section>
    </PageContainer>
  );
}
