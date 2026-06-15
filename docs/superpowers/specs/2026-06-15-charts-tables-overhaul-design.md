# 图表 / 表格 / 图标全面专业化升级 — 设计 Spec

**日期**: 2026-06-15
**分支**: `feat/charts-tables-overhaul`
**范围**: 仅前端 `frontend/src` 呈现层。**不动** `simulator/`、`backend/`、任何数值/口径/成功率逻辑。

---

## 1. 目标与非目标

### 目标
- 显著提升全站**图表、表格、图标**的专业度与一致性,改善用户体验。
- 把散落各页的 chrome(标题/控制/下载/排序/格式化)**收口到统一抽象**,消除 3 套表格实现、硬编码色、误导坐标轴、缺失 hover、裸 Unicode 符号、重复代码。
- 引入"可用的深色模式 + 直接标注 + 骨架屏/空状态 + 图表数据导出 + 分布优先呈现"等新能力。

### 非目标(行为保真)
- 不改任何模拟数值、口径、API schema、成功率 / funded ratio / censored 逻辑。
- 不重排页面信息架构(除"统计摘要"按本 spec 改为分布优先;其余页面布局不动)。
- 不引入新的后端依赖。

---

## 2. 已锁定的设计决策(经 mockup 确认)

| 项 | 决策 |
|---|---|
| **调色板** | 方案 B「精炼专业」。`primary #2f6bd8`(rgb 47 107 216)/ `success #0e9f6e` / `danger #d64550` / `warning #d99a3d` / `accent #6d5bd0` / `neutral #7b8494` / `orange #dd6b33`。深色模式同色相,仅文字/网格/hover/paper 随主题。|
| **连续色阶** | funded-ratio 用 **RdYlBu 反向**(红=差→蓝=好),色盲友好且呼应主色。替换 `RdYlGn`。|
| **表格样式** | 方案 A「通透极简(Stripe 风)」:发丝级行分隔、无斑马纹、hover 高亮、最佳/最差用左色条。|
| **深色模式** | `next-themes`(`attribute="class"`、`defaultTheme="system"`、防闪烁)+ navbar 切换(Sun/Moon/Monitor)。图表经 `PlotlyChart` 单点适配。|
| **新能力(全部纳入)** | ① 直接标注 ② 骨架屏 + 空状态 ③ 图表数据导出 ④ 可用深色模式 ⑤ DistributionStrip(分布优先呈现统计摘要)。|
| **StatsTable** | 保留"按列渲染 + 后端预格式化字符串"逻辑;只换样式 A + 自动识别数字列右对齐(等宽数字)+ 负值/关键值语义着色 + sticky + 深色。**不**并进可排序 DataTable。|
| **分期** | 单分支 `feat/charts-tables-overhaul`,P0–P5 阶段性 commit,每期一轮 Codex 评审,最后整体 `--no-ff` 合 main。|

---

## 3. 架构:新增 / 改造的共享件

### 3.1 `lib/chart-theme.ts` 重写(主题中枢)
- `CHART_COLORS` → 调色板 B(每色 `.hex` + `.rgb` 双形态,沿用现接口以减小迁移面)。
- **深色感知**:`mergeLayout(custom, isDark)` 接收主题标志;内部按主题给出:
  - `font.color`、`xaxis/yaxis.tickfont.color`、`axisBase.title.font.color`
  - `yaxis.gridcolor`(浅:`rgba(0,0,0,0.06)`;深:`rgba(255,255,255,0.08)`)
  - `hoverlabel.bgcolor/bordercolor/font.color`
  - `paper_bgcolor/plot_bgcolor` 保持 transparent(继承 Card 背景)。
- `PlotlyChart` 内 `useTheme()` 读 `resolvedTheme`,传 `isDark` 给 `mergeLayout`/`mergeConfig`;主题切换时 next-themes 触发 re-render,图表自动重绘。
- 新增导出常量(消灭魔法值):
  - `FUNDED_RATIO_COLORSCALE`(RdYlBu 反向,Plotly colorscale 数组)
  - `CATEGORICAL: string[]`(有序多系列色,供堆叠/分组柱图,如 buy-vs-rent 成本拆解)
  - `BAND_OPACITIES`(扇形带:`[0.14, 0.30]`)
  - `MARKER_SIZES`(allocation 点/星等级)
  - `CHART_HEIGHTS = { sm, md, lg }`(取代 260/280/300/380/400/450 散值;含 mobile 变体)
- 保留 `MARGINS` 预设;新增 scenario/tornado 用的长标签左边距预设(取代页面内魔法 margin 对象)。
- **(Codex)** `mergeLayout` 只覆盖默认 x/y 轴 + legend,**不会自动主题化自定义子布局**——`PlotlyChart` 单点改造 ≠ 所有图表深色就绪。须额外提供themed helper 并审计调用点:`themedTernary()`(allocation 三元图网格/轴/legend 背景,现硬编码 `rgba(0,0,0,0.08)`/白)、`themedColorbar()`、`themedAnnotations()`、`themedAxis2()`(护栏/买vs租 dual-axis 的 `yaxis2`)。**P0 的"图表深色"在这些 call site 审计完成前不算 done。**
- **(Codex)** 保留现有 Plotly bundle 策略:`plotly.js/lib/core` 动态导入 + 仅注册 `scatter/scatterternary/bar`(见 `plotly-chart.tsx:8-17`)。重写 chart-theme **不得**误引入完整 `plotly.js`。

### 3.2 `components/chart-frame.tsx`(新,图表统一外壳)
Props: `title`、`infoTooltip?`、`height?`(sm/md/lg)、`showLogToggle?`、`logState?`、`onToggleLog?`、`downloadPng?`、`downloadData?: () => Row[]`、`loading?`、`isEmpty?`、`emptyHint?`、`children`(图表)。
- 渲染:标题行(左标题 + 可选 info)+ 右上控制区(对数切换[**带 aria-label**]、下载菜单 = PNG[带标题] + 数据 CSV)。
- `loading` → `<ChartSkeleton height>`;`isEmpty` → `<EmptyState>`。
- 统一移动端标题/高度/`displayModeBar` 策略。
- 现有 `FanChart`/各页 PlotlyChart 调用点包进 ChartFrame。
- **(Codex)** `FanChart` 现在**自持** `logScale` state + 自带按钮(`fan-chart.tsx:60,122-148`),wrapper 无法直接接管。**P1 须先把 FanChart 重构为受控**(`logScale` / `onLogScaleChange` props),再由 ChartFrame 提供控制区、迁移调用点。

### 3.3 `components/data-table.tsx` + `components/ui/status-badge.tsx`(新,统一表格)
`DataTable<T>` 列定义驱动:
```
type Column<T> = {
  key: string; header: ReactNode;
  align?: "left" | "right";
  sortable?: boolean;
  sortValue?: (row: T) => number | string | null;   // null 排序见下
  render?: (row: T) => ReactNode;                    // 默认 String(row[key])
  csvValue?: (row: T) => string;                     // 见下:CSV 导出对齐
  className?: string;
}
type DataTableProps<T> = {
  columns: Column<T>[]; rows: T[];
  onRowClick?: (row: T) => void;                     // 见下:路径表下钻
  rowClassName?: (row: T) => string;                 // 最佳/最差左色条
  downloadName?: string; maxHeight?: number; emptyHint?: ReactNode;
}
```
内建:点列头排序(`aria-sort` + lucide `ChevronUp/ChevronDown`/中性图标)、sticky 表头、CSV 导出(复用 `lib/csv`)、空状态、数字列 `tabular-nums` 右对齐。
**(Codex)三处必须在 P1 定死的行为契约,否则 P2 迁移会撞上缺失 API:**
- **行下钻**:`onRowClick` + 键盘可达(`role="button"`/`tabIndex=0`/Enter·Space)+ hover/cursor 语义。simulator(`simulator-client.tsx:785-789`)与 guardrail(`guardrail/page.tsx:1062-1067`)路径表点行打开明细,必须保留。
- **CSV 对齐**:`csvValue` 默认取渲染文本;**导出当前排序/过滤后的行序**,表头用已翻译文案(对齐 allocation `allocation/page.tsx:367-394` 的 `notDepleted` 等本地化导出)。
- **null 排序**:统一"**null 永远排末**(升降序皆然)"。这与 allocation 现状 `null→Infinity`(降序时 null 反而在首,`allocation/page.tsx:51-57`,`p10_depletion_year` 可空)不同 —— **这是一处有意的修正,非保真**,在本 spec 显式声明,并对每个可空列做迁移核对。
`StatusBadge variant="ok|bad|censored"`:彩色 pill(✓成功 / ✗失败 / ?截尾)替代裸 Unicode,**带文字 + aria-label**。
**替换目标**:simulator + guardrail 批量回测路径表(×2)、情景表(×2)、敏感性表(×2)、allocation 结果表、guardrail 调整事件日志表、`CountrySuccessTable`。

### 3.4 `components/stats-table.tsx` 重样式(保留逻辑)
- 套样式 A;**自动识别数字列**(列内所有非首列值匹配 数字/百分比 → 右对齐 + 等宽)。
- 语义着色:负值(如最大回撤)`danger`;成功率等关键值可选高亮(由调用方传 `emphasizeKeys?`)。
- sticky 表头 + 深色适配。CSV 按钮沿用。

### 3.5 `components/distribution-strip.tsx`(新,分布优先)
- 输入:`{ min, p5, p10, p25, p50, p75, p90, p95, max, mean }`(real 金额)。
- SVG 横向对数刻度分位带:浅带 P10–P90、深带 P25–P75、须 P5–P95、虚线箭头→max、中位蓝线、均值橙菱、0 破产红块。
- **(Codex)对数刻度边界必须在 P1 用纯函数 scale helper 处理 + 推理覆盖**(失败/耗尽路径会产生这些情形):
  - `min=0`(或任意 ≤0):**单独的"0 桶"标记**(红块,不进 log 映射),正值部分用正域 log;
  - **所有百分位相等 / 区间极小**:退化为单点/极窄带,不除零、不产生 NaN 宽度;
  - **缺失百分位 key**:跳过该标记而非崩溃;
  - **移动端窄宽**:标签按 §3.5 去碰撞规则降级。
  数据来源 `SimulationResponse.final_min/final_percentiles`(`lib/types.ts:76-83`)。
- **直接标注去碰撞规则(硬性)**:仅 `中位 + 两端(0 / 最高)` 内联;`均值 / P10 / P90` 等次要标记 → 说明行或 hover;两内联标签间距 < 阈值则纵向错位或省略。**同规则适用于扇形图末端标签。**
- 下方说明行:band 图例 + 均值数值/偏态解读 + "对数刻度·实际金额·N 次模拟" + `▸ 展开精确数值`(可展开 = 重样式 StatsTable,右对齐 + CSV)。
- 用于:主页「统计摘要」替代长表(去掉与 MetricCard/verdict 重复的 成功率/均值/中位 行,模拟次数降为注脚);批量回测期末资产分布可复用。

### 3.6 深色模式基建
- 新增 client `components/providers.tsx`(`<ThemeProvider>`),`app/layout.tsx` `<html suppressHydrationWarning>` 包裹。
- navbar 加切换按钮(三态 system/light/dark)。
- **(Codex)硬编码浅色面板审计须全仓库,不止 allocation**:已知遗漏点含 accumulation amber 警示(`accumulation/page.tsx:313-315`)、allocation error card(`allocation/page.tsx:140-143`)、CountrySuccessTable tag 色(`country-success-table.tsx:125-137`)、allocation 行高亮 `bg-green-50`/`bg-amber-50`。grep `bg-(green|amber|red|blue)-50`、`#fff`、`rgba(255` 全量过一遍。
- **(Codex)PDF 导出深色安全前移到 P0/P1**(原计划 P3,太晚):`pdf-export.ts:11-14` 用 `backgroundColor:"#ffffff"` 截 `#sim-results`/`#guardrail-results`,但深色 token 仍作用于子元素 → 深色下导出会"白底深字"破版。策略:**捕获时强制浅色克隆**(临时去 `.dark` / 包一层 `light` class)或显式按当前主题导出 + 匹配背景。P0/P1 落地此策略,P5 验证。

### 3.7 骨架屏 / 空状态
- `components/ui/skeleton.tsx`(shadcn skeleton)+ `ChartSkeleton`/`TableSkeleton` 包装;`components/empty-state.tsx`(图标 + 文案)。
- 计算中 charts/tables 显示 skeleton(与现 ProgressOverlay 协调,不冲突);无结果显示 EmptyState 替代当前裸文本 placeholder。

### 3.8 图标规范(lucide)
- 统一尺寸刻度(`h-3.5 w-3.5` 行内 / `h-4 w-4` 默认)、统一描边。
- Unicode `↑↓ ▲▼` 排序箭头 → lucide 图标;裸 `✓✗?` → StatusBadge。
- 克制地补语义图标:PlanVerdict 横幅(CheckCircle/AlertTriangle/XCircle)、MetricCard、tab、章节标题。不滥用。

### 3.9 数字格式统一
- 概率一律 `pct()`;金额一律 `fmt()`。清除内联 `(x*100).toFixed(1)%`、`toLocaleString(...)`。
- 去重:`fmtVal`(simulator/guardrail 各一份)、`handleSort/sortIndicator`、buy-vs-rent fanTraces band 逻辑(并入共享 helper 或 ChartFrame/DataTable)。

### 3.10 坐标轴 / hover 修正(随图表迁移)
- 龙卷风图 x 轴 `ticksuffix:"%"` → 正确标 `pp`(百分点);单位与 hover 对齐。
- 给 sensitivity / accumulation / buy-vs-rent 简单模式补 `hovertemplate`;补 guardrail 基准线缺失的 hover。
- 统一各等价图的高度与 `displayModeBar`。

### 3.11 i18n(新增 UI 字符串)— **(Codex)P1 验收项**
新组件引入的所有可见文案必须在 `messages/en.json` + `messages/zh.json` **双语同步补齐**(仓库现状 ~803 key 严格对齐):
- `chartFrame.*`(下载 PNG / 下载数据 / 对数·线性切换 aria-label 等)
- `distributionStrip.*`(中位/均值/分位/破产下限/最高/展开精确数值/对数刻度·实际金额 等)
- `theme.*`(system / light / dark 切换 aria-label)
- `emptyState.*`(各页空状态文案)、`statusBadge.*`(成功/失败/截尾 + aria-label)
新字符串一律走 `next-intl`,**不得硬编码中文/英文**到组件。

---

## 4. 分期计划(每期独立可审、可单独 commit;每期跑 Codex 评审)

| 期 | 内容 | 验证 | 风险 |
|---|---|---|---|
| **P0 基础** | chart-theme 重写(palette B / 深色 token / 色阶 / 常量 + themed 子布局 helper)+ next-themes Provider + navbar 开关 + **PDF 深色捕获策略** + **全仓库硬编码浅色面板审计** | build+lint;浅/深肉眼 + PDF 浅/深导出 | 低–中 |
| **P1 组件** | ChartFrame / DataTable / StatusBadge / Skeleton / EmptyState / DistributionStrip;**FanChart 重构为受控 log**;**定死契约**(onRowClick+键盘 / csvValue+排序后导出 / null-last / log-scale 边界)+ **i18n 双语 key** | build(含 tsc)+lint;纯函数 helper(排序比较、数字列识别、对数定位含 min=0/退化、去碰撞阈值)可独立推理 | 低(新增) |
| **P2 表格迁移** | 8 张表换 DataTable + StatsTable 重样式 + 格式统一 + 图标箭头/StatusBadge | build+lint;逐页核对数据一致 | 中 |
| **P3 图表迁移** | 全图入 ChartFrame、去硬编码色、色阶替换、修轴/hover、直接标注、统计摘要换 DistributionStrip | build+lint;逐图核对 | 中 |
| **P4 图标+收尾** | 图标规范统一、skeleton/空状态接线、图表数据导出菜单 | build+lint | 低 |
| **P5 QA** | 深色模式全站走查 + a11y(aria-sort/aria-label/对比度)+ `next build` + `eslint` + `pytest`(确认未碰后端)+ 用户本地浅/深验收 + Codex 终审 | 全量 | — |

---

## 5. 验证与回归
- 每期:`(cd frontend && npx next build)`(含 TypeScript 类型检查)+ `(cd frontend && npx eslint src/)`。
- 全程至少跑一次 `pytest tests/` 确认后端零改动未被波及。
- 前端无 JS 单测框架(仓库现状:仅 build + eslint)。新组件以 **类型检查 + 纯逻辑 helper 抽离 + dev server 手测** 覆盖;不为本次升级引入测试框架。
- P5 启 dev server(后端 8888),用户肉眼验收浅色 + 深色两套。

## 6. 风险与缓解
- **深色模式图表可读性**:深色 token 需保证对比度;P5 专项走查。
- **Plotly 主题切换重绘**:确认 next-themes 的 `resolvedTheme` 变化触发 PlotlyChart re-render(必要时 key 绑定 theme)。
- **DataTable 迁移回归**:每表迁移后逐列核对排序/格式/最佳最差与旧版一致(尤其 censored 三态、护栏 G/B 双列)。
- **直接标注碰撞**:按 3.5 规则,内联仅中位+两端,其余入说明行/hover。
- **PDF 导出**:`pdf-export` 针对 `#sim-results` 截图;深色模式下导出建议强制浅色(P3 验证)。

## 7. 开放问题
- 无阻塞项。(前端测试框架现状已确认:无,见 §5。)

## 8. Codex 评审吸收记录(2026-06-15)
对初版 plan 跑了一轮独立 Codex 评审(读真实代码)。10 条 finding **全部认同并已并入上文**,核心修正 = "把被当成样式的行为契约提前到 P1 定死":
| # | 级别 | finding | 处理 |
|---|---|---|---|
| 1 | HIGH | DistributionStrip 对数刻度对 0/退化/缺 key 无规则 | §3.5 加纯函数 scale helper + 边界规则 |
| 2 | HIGH | DataTable 缺路径表行点击/键盘下钻 | §3.3 加 `onRowClick` + 键盘可达 |
| 3 | HIGH | DataTable CSV 无法保真现有导出 | §3.3 加 `csvValue` + 导出排序后行序 |
| 4 | HIGH | PDF 导出深色不安全、分期太晚 | §3.6 前移到 P0/P1 + 强制浅色捕获 |
| 5 | HIGH | mergeLayout 不覆盖自定义子布局(三元/colorbar/legend/yaxis2) | §3.1 加 themed helper + call-site 审计 |
| 6 | MED | ChartFrame 与 FanChart 自持 log state 冲突 | §3.2 P1 先把 FanChart 改受控 |
| 7 | MED | null 排序语义与 allocation 现状(null→Infinity)冲突 | §3.3 声明为**有意修正**(null-last)+ 逐列核对 |
| 8 | MED | 新 UI 字符串无 i18n 清单 | §3.11 P1 双语 key 验收项 |
| 9 | MED | 深色硬编码色审计太窄 | §3.6 改为全仓库审计 |
| 10 | LOW | 未声明保留 Plotly bundle 策略 | §3.1 加 core 动态导入约束 |

**Codex 结论**:方向正确(ChartFrame + 谨慎 scoped DataTable + 中央主题是这 6 页的对的抽象);最大风险是把行为契约当样式做 —— 已通过 P1 契约强化消解。
