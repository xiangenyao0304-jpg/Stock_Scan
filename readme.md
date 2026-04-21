# Stock_Scan

多市场选股雷达项目，包含：

- `backend/`：FastAPI + AkShare + 本地缓存 + 定时预热
- `frontend/`：React + Vite + `lightweight-charts`
- `backend/warm.py`：按市场刷新数据并重跑默认扫描

当前支持 4 个市场：

- A 股
- 港股
- 美股
- 主题股池

## 功能概览

- 动能扫描：输出 `看涨 / 看跌` 信号
- HMM 选股：先判断市场状态，再做多因子打分
- K 线详情：展示 K 线、均线、布林带、MACD、MF 结构和背离
- 定时刷新：每个市场收盘后自动抓新数据并重跑默认扫描

## 本地启动

### 后端

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

默认后端地址：

- `http://127.0.0.1:8000`

### 前端

```bash
cd frontend
npm install
npm run dev
```

默认前端地址：

- `http://127.0.0.1:5173`

开发模式下 Vite 已代理 `/api` 到本地后端。

## 生产部署说明

当前线上部署方式是：

- `nginx` 对外提供前端静态文件
- FastAPI 在服务器本地端口运行
- `systemd timer` 按市场定时执行 `backend/warm.py`

定时流程是：

1. 刷新市场缓存
2. 立刻重跑默认动能扫描
3. 立刻重跑默认 HMM 扫描
4. 将结果写入缓存文件供前端读取

## GitHub Pages

仓库内已提供 GitHub Pages 自动部署工作流：

- 文件：`.github/workflows/deploy-pages.yml`
- 触发方式：push 到 `main` 后自动部署前端

GitHub Pages 只负责前端静态页面，不能运行 FastAPI 后端。

### 重要限制

前端页面要真正可用，必须能访问一个可跨域调用的后端 API。

仓库里的前端已经支持通过环境变量 `VITE_API_BASE` 指定后端地址，例如：

```text
https://your-api-domain.com
```

前端最终会请求：

- `https://your-api-domain.com/api/scan`
- `https://your-api-domain.com/api/hmm_scan`
- `https://your-api-domain.com/api/kline`

### 为什么不能直接填你的当前服务器地址

GitHub Pages 是 `https` 页面。

如果后端还是纯 `http`，浏览器会因为 mixed content 直接拦截请求。

所以你需要：

1. 给后端配一个 `https` 域名，或者
2. 给服务器上的 `nginx` 配 HTTPS 证书

然后在 GitHub 仓库里设置 Actions 变量：

- 路径：`Settings` -> `Secrets and variables` -> `Actions` -> `Variables`
- 新建变量名：`VITE_API_BASE`
- 变量值示例：`https://api.your-domain.com`

### 启用 GitHub Pages

在 GitHub 仓库里：

1. 打开 `Settings`
2. 打开 `Pages`
3. Source 选择 `GitHub Actions`

之后每次 push 到 `main`，前端都会自动发布到：

- `https://xiangenyao0304-jpg.github.io/Stock_Scan/`

## 目录结构

```text
Stock_Scan/
├── backend/
│   ├── main.py
│   ├── scanner_hmm.py
│   ├── warm.py
│   ├── requirements.txt
│   ├── universes/
│   └── launchd/
├── frontend/
│   ├── package.json
│   ├── vite.config.js
│   ├── public/
│   └── src/
├── .github/workflows/
└── README.md
```

## 额外说明

- `Readme2.md` 保留了 HMM 方案的原始需求说明
- `RUNNING.md` 记录了本地运行方式
- `backend/launchd/` 是 macOS 的定时任务样例

