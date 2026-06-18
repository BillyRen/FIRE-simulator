# devport — 全局本地 dev 端口分配工具（设计 spec）

日期：2026-06-18
状态：设计已敲定，已过一轮 Codex review 收敛，待实现

## 1. 背景与动机

本机 `~/Projects` 下多个 web 项目（FIRE_simulator / china_factor_backtest / wealth_analyzer / meridian / paper-search-mcp 等）默认都监听 3000（前端）和各自的后端端口，反复端口冲突。

实证踩坑（2026-06-17）：china_factor 前端占着 3000，FIRE 前端被迫起到 3001；但 FIRE 后端 `ALLOWED_ORIGINS` 默认只允许 `localhost:3000`，浏览器拦掉 3001→8888 的跨域请求，UI 表现为"后端没启动"（curl 测返回 200 是因 curl 不受 CORS 限制，一度误判）。

目标：一个全局、确定性、可扩展到多应用的本地端口分配方案，**杜绝已注册项目之间的端口冲突**，并把 CORS 联动纳入考量。（诚实边界：只覆盖接入 devport / 已预填充的项目；完全消除全机冲突需所有活跃项目都登记，见 §6。）

约束：本机 8000 与 8888 被高德地图服务占用，后端端口范围必须避开。

## 2. 核心模型：哈希 + 注册表（混合）

每个应用分到一个 **10 端口块**：

```
slot 空间:   0 .. 49           (减去 reserved 后 ~45 个可用)
前端 base:   3000 + slot*10    → 3000..3490   (范围 3000-3499)
后端 base:   9000 + slot*10    → 9000..9490   (范围 9000-9499，避开 8000/8888)
块内偏移:    +0 = 主 checkout    +1..+9 = worktree (套用现有 worktree.sh 的 base+n 逻辑)
```

### 2.1 RESERVED_SLOTS（跳过的槽，避开常见服务）
自动分配（哈希探测）时跳过这些槽；仅显式 `pin` 可占用：
```
0  → fe 3000 (grafana/node/react 通用) + be 9000 (SonarQube/php-fpm)。也是 china_factor 现占位
9  → be 9090 (Prometheus)
20 → be 9200 (Elasticsearch HTTP)
22 → be 9220-9229 块含 Chrome DevTools 远程调试 9222/9229
30 → be 9300 (Elasticsearch transport) + fe 3300-3309 块含 MySQL 3306
```
常量集中定义，后续可扩展。可用槽 = 50 − 5 = 45。

### 2.2 应用名归一化（canonical slug）
哈希前先归一化，避免 `FIRE_simulator` 与 `fire` 哈希到不同块：
```
slug = app.strip().lower()，非 [a-z0-9] 字符 → 连字符，首尾连字符去除
```
每个项目在集成侧传**字面量 canonical slug**（FIRE = `fire`），不依赖目录名推导。

### 2.3 分配算法（首次遇到某 slug）
**整个读-探测-写全程持锁**（见 §2.4），不只是写：
1. 持锁
2. 读注册表 `~/.config/devports/registry.json`
3. 若 slug 已存在 → 直接返回（幂等）
4. `preferred = sha1(slug) % 50`
5. 线性探测：`for i in range(50): cand = (preferred + i) % 50`，跳过 RESERVED_SLOTS 和注册表已占用的槽，取第一个空槽
6. 50 次探测仍无空槽 → 报 `registry full` 错误（非 0 退出）
7. 写回 `{slug: {"slot": cand}}`，原子替换文件，释放锁

之后每次调用直接读注册表 → 同一 slug 永远拿同一块（确定性、零碰撞）。探测只看**注册表占用**，不看实时 OS 端口（保证同一 app 端口稳定）；块内 +1..9 的实时占用检查交给 `worktree.sh` 的 `lsof`（它已经在做）。

### 2.4 锁（macOS 无 flock，用 mkdir 原子锁）
- 锁 = `~/.config/devports/.lock` 目录；`mkdir` 成功即持锁。
- 锁目录内写 `owner` 文件，含 `pid + hostname + timestamp`。
- 获取失败时读 owner：**仅当**（同主机且 PID 已不存在）**或**（timestamp 超过保守阈值，如 30s）才判定为陈旧并破锁；破锁后重新 `mkdir`，成功后**再次校验** owner 是自己。
- 正常路径 `try/finally` 删锁。
- 单人开发并发分配极少，此机制足够。

### 2.5 注册表只存 slot（派生字段每次推导）
注册表只持久化 `slot`（+ 可选 `updated_at` 元数据）。`fe/be` 每次读取时由 `slot` + base 常量推导，避免常量变更或手动编辑导致内部不一致：
```json
{ "fire": {"slot": 7}, "china_factor": {"slot": 0} }
```

## 3. CLI 形态（纯查询，不带启动器）

实现语言 **Python 3**（hashlib + JSON + mkdir 锁；miniforge python3 全局在 PATH）。安装到 `~/.local/bin/devport`。

```
devport <app>              # stdout: FRONTEND_PORT=3070 BACKEND_PORT=9070   (可直接 eval)
devport <app> --json       # {"app":"fire","slot":7,"fe":3070,"be":9070}
eval "$(devport fire --shell)"   # 导出 FRONTEND_PORT / BACKEND_PORT
devport <app> --cors [--offset N]  # 输出该 checkout 的 CORS origin 串 (见 §4)
devport list               # 表格列出全部注册表
devport pin <app> <slot>   # 手动钉死某槽（槽被占或非法则报错；可占 reserved 槽）
devport rm <app>           # 释放某 app 的槽
```
退出码：成功 0；注册表满 / 槽冲突 / 参数错误 非 0，stderr 给原因。所有命令对 app 名做 §2.2 归一化。

## 4. CORS 联动

每个后端**只信任自己 checkout 的前端 origin**（不是整块 20 个）——因为每个 worktree 各跑各的前后端（worktree.sh 同时起两者）。

`devport <app> --cors [--offset N]` 输出（N 为 worktree 偏移，主 checkout=0）：
```
http://localhost:<fe_base+N>,http://127.0.0.1:<fe_base+N>
```
即 2 个 origin，**带 `http://` scheme**。集成侧把它喂给后端 `ALLOWED_ORIGINS`。

## 5. 本次落地范围（opt-in，先接 FIRE）

1. 新建 `~/.local/bin/devport`（Python，含归一化、RESERVED_SLOTS、mkdir 锁、线性探测、list/pin/rm/--json/--shell/--cors），`chmod +x`。
2. **预填充注册表**：
   - `pin china_factor 0`（它现在活在 3000，占位 + 记录真实占用）
   - `devport fire` / `wealth_analyzer` / `meridian` / `paper-search-mcp`（哈希分配），记录各自 slot 并报告。
3. 改 FIRE `scripts/worktree.sh`：硬编码 `3000/8888` 换成读 `devport fire`（base+n 逻辑不变）。后端启动用 `devport fire --cors --offset $n` 生成 `ALLOWED_ORIGINS`。加 `DEVPORT_BIN=${DEVPORT_BIN:-$HOME/.local/bin/devport}` 查找，**不存在时打印可执行错误提示并回退到硬编码 3000/8888**。
4. 改 FIRE `dev` skill / 启动命令同理（前端 `PORT`/`NEXT_PUBLIC_API_URL`、后端 `ALLOWED_ORIGINS`），同样带 fallback。
5. 其他项目暂不改 dev 脚本（已预填充槽，互不撞），以后用到再接。

## 6. 已知盲区与权衡

- **opt-in 盲区**：注册表只保证已注册 app 间零碰撞。未登记的项目对 devport 不可见 → 靠"预填充所有已知活跃项目"缓解。目标措辞已诚实降级（§1）。
- **哈希碰撞**：纯哈希会碰撞，故注册表线性探测兜底；代价是多一个 `~/.config` 状态文件。
- **FIRE 端口变化**：FIRE 历史用 3000/8888。接入后改为哈希块（如 fe 3070 / be 9070）+ fallback。用户要回固定值可 `devport pin fire <slot>`；be 范围 9000-9499 无法精确还原 8888（8888 本就是绕开 AMap 8000 的临时值，不神圣）。
- **跨项目原子性**：单人开发并发分配极少，mkdir 锁足够。
- **锁 TOCTOU 残留窗口（已接受）**：`release_lock` 用 UUID token 校验所有权后才删锁，消除了"A 超时→B 破锁重获→A 误删 B 锁"的主竞态；但「读 owner→删除」之间及 stale-break 路径仍有理论上的毫秒级 TOCTOU 窗口。本地 CLI 端口分配场景概率极低，判定可接受，不再加重量级锁（Codex 第三轮确认）。

## 7. 测试要点

- 归一化：`FIRE_simulator`/`fire`/`FIRE` → 同一 slug 同一块。
- 哈希确定性：同一 app 多次调用返回同一块。
- 碰撞探测：两个哈希到同槽的 app，第二个落到下一空槽且跳过 reserved。
- reserved 跳过：自动分配永不落在 {0,9,20,22,30}；`pin` 可占。
- 注册表满：45 个可用槽占满后第 46 个报 registry-full。
- 持久化 + 锁：跨进程一致；并发两进程首次分配同一 app 不重复分配（持锁全程）；陈旧锁（PID 已死）可被安全破除。
- 派生一致性：手改 registry 只动 slot，fe/be 仍正确推导。
- 端口范围不变量：fe ∈ [3000,3499]、be ∈ [9000,9499]、自动分配永不命中 3000/9000/9090/9200/9222/9229/9300/3306。
- CORS：`--cors --offset N` 输出带 http:// 的 2 个 origin（localhost + 127.0.0.1，端口含偏移）。
- pin/rm：pin 占用槽报错、rm 后槽可复用。
- FIRE 集成：worktree.sh 主 checkout 用 base+0、worktree 用 base+n；devport 缺失时回退硬编码并提示。
