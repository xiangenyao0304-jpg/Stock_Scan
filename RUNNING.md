# 启动指南

## 1. 后端（FastAPI + AkShare）

```bash
cd backend
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python main.py                 # 或: uvicorn main:app --reload --port 8000
```

服务启动后：
- API 文档: <http://127.0.0.1:8000/docs>
- 扫盘接口: <http://127.0.0.1:8000/api/scan>
- K线接口: <http://127.0.0.1:8000/api/kline?code=600519>

> 首次调用 `/api/scan` 会并发拉取约 30 只股票数据，耗时约 10–30 秒。可在 `main.py` 的 `DEMO_POOL` 中自行扩充至沪深 300 全量。

## 2. 前端（React + Vite + lightweight-charts）

```bash
cd frontend
npm install
npm run dev
```

访问 <http://localhost:5173>。Vite 已配置 `/api` 代理到后端 8000 端口，无需额外 CORS 配置。

## 3. 项目结构

```
Stocks_Scan/
├── backend/
│   ├── main.py              # FastAPI + 量化逻辑
│   └── requirements.txt
├── frontend/
│   ├── index.html
│   ├── package.json
│   ├── vite.config.js
│   └── src/
│       ├── main.jsx
│       ├── App.jsx          # 主从布局 + 列表
│       ├── App.css
│       └── ChartComponent.jsx  # 主副图 + 联动
└── readme.md
```

## 4. 核心逻辑速览

- **数据预热**：拉取近 150 个交易日，仅用最近 40 日状态做信号判定。
- **看涨（模型 A）**：MA20 压制 MA50 上方 + 布林缩口 + 价稳中轨 + 量价配合 + MACD 零轴金叉。
- **看跌（模型 B）**：MA20 拐头/死叉 + 布林缩口 + 跌破中轨 + 放量下跌缩量反弹 + MACD 水下死叉。
- **并发与重试**：`ThreadPoolExecutor(MAX_WORKERS=8)` + `tenacity` 指数退避三次重试。
