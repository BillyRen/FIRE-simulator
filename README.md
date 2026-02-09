# FIRE 退休模拟器

基于蒙特卡洛模拟的退休规划工具，使用历史美股/国际股票/美债回报数据，通过 Block Bootstrap 采样评估退休方案的成功概率。

## 在线访问

- **前端**: https://frontend-six-nu-41.vercel.app
- **后端 API**: 部署在 Render（见下方部署说明）

## 本地运行

需要同时启动后端和前端：

**后端 (FastAPI)**
```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --port 8000
```

**前端 (Next.js)**
```bash
cd frontend
npm install
npm run dev
# 打开 http://localhost:3000
```

## 功能模块

### 退休模拟器
- 蒙特卡洛模拟（Block Bootstrap）
- 固定/动态提取策略（Vanguard Dynamic Spending）
- 资产轨迹扇形图、统计摘要
- 自定义现金流（收入/支出，通胀调整）
- 杠杆组合模拟

### 敏感性分析
- 提取率扫描：不同提取率对应的成功率曲线
- 资产扫描：达到目标成功率所需的初始资产

### 风险护栏策略
- Risk-based Guardrail：基于成功率动态调整提取金额
- 金额调整/成功率调整两种模式
- 历史回测：选择起始年验证策略在真实市场中的表现

### 最优资产配置
- 扫描不同资产配置组合的模拟表现
- 三元热力图可视化

## 部署

### 前端（Vercel）

已部署到 Vercel。每次推送到 `main` 分支会自动重新部署。

设置环境变量：
- `NEXT_PUBLIC_API_URL` = 你的 Render 后端 URL

### 后端（Render）

1. 打开 https://dashboard.render.com
2. 点击 **New** → **Blueprint**
3. 连接 GitHub 仓库 `BillyRen/FIRE-simulator`
4. Render 会自动读取 `render.yaml` 并创建服务
5. 等待构建完成

或者手动创建：
1. 点击 **New** → **Web Service**
2. 连接 GitHub 仓库
3. Build Command: `pip install -r backend/requirements.txt`
4. Start Command: `cd backend && uvicorn main:app --host 0.0.0.0 --port $PORT`
5. 添加环境变量 `ALLOWED_ORIGINS` = 你的 Vercel 前端 URL

## 技术架构

```
FIRE_simulator/
├── simulator/          # 计算引擎（Python）
│   ├── bootstrap.py    # Block Bootstrap 循环采样
│   ├── portfolio.py    # 组合回报计算
│   ├── monte_carlo.py  # 蒙特卡洛模拟
│   ├── statistics.py   # 统计分析
│   ├── sweep.py        # 敏感性扫描
│   ├── guardrail.py    # Guardrail 策略
│   ├── cashflow.py     # 自定义现金流
│   └── config.py       # 全局常量
├── data/               # 历史回报数据 (1871-2025)
├── backend/            # FastAPI REST API
│   ├── main.py         # API endpoints
│   └── schemas.py      # Pydantic 数据模型
├── frontend/           # Next.js + React 前端
│   └── src/
│       ├── app/        # 4 个页面
│       ├── components/ # 共享组件
│       └── lib/        # API 客户端 + 类型定义
└── render.yaml         # Render 部署配置
```

## 数据来源

`data/FIRE_dataset.csv` 包含 1871-2025 年的年度回报数据：
- US Stock（美股）
- International Stock（国际股票，1970 年前由美股模拟）
- US Bond（美债）
- US Inflation（通胀率）

## 多语言支持

支持中文和英文，自动检测浏览器语言，也可手动切换。
