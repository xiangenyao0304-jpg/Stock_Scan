**【角色设定】** 你现在是一位拥有 10 年经验的资深金融量化工程师兼全栈开发专家。你精通 Python 数据分析（Pandas, pandas-ta）、熟悉 A 股与港股的开源数据生态，并且擅长使用现代前端框架（Vue3 或 React）和图表库（Lightweight Charts）构建交互式金融看板。

**【项目概述】** 我需要开发一个“A股/港股 动能扫盘雷达” Web 应用程序。采用前后端分离的主从架构（Master-Detail）。

- **功能目标：** 每天扫描全市场，筛选出符合特定量化形态（分为“蓄势待发看涨”和“摇摇欲坠看跌”）的股票列表。用户在前端点击列表中的股票，可以直接在下方看到带有技术指标的交互式 K 线图。

**【技术栈选型与约束】**

1. **后端框架：** Python (FastAPI)。
2. **数据源：** 强制使用开源库 `AkShare`（使用日线级别数据接口，如 `stock_zh_a_hist`）。
3. **指标计算库：** `pandas` 与 `pandas-ta`。
4. **前端框架：** 请选择 Vue3 (Composition API) 或 React (Hooks) 提供代码。
5. **前端图表库：** 强制使用 TradingView 开源的 `lightweight-charts`。
6. **性能要求：** 后端拉取全市场数据必须使用并发（如 `concurrent.futures`）并包含异常重试（Retry）机制，以应对 AkShare 接口限流。

**【后端核心量化逻辑（双向模型）】** 在执行扫盘时，请为每只股票拉取**过去 150 个交易日**的日线数据（用于指标预热），但仅根据**最近 40 个交易日**的数据状态进行以下判定：

- **模型 A：蓄势待发（看涨突破）**
  - *趋势：* 近 40 日内，20 日均线（MA20）总体运行在 50 日均线（MA50）上方。
  - *形态：* 布林带（20, 2）近期出现明显缩口（带宽降至近半年低位区间），且最新价格企稳在布林带中轨附近或上方。
  - *动能：* 近期上涨日成交量大于下跌日成交量（量价配合好）；MACD 在零轴附近即将发生金叉或刚刚水上金叉。
- **模型 B：摇摇欲坠（看跌破位）**
  - *趋势：* 近 40 日内，MA20 开始拐头向下，或已死叉 MA50。
  - *形态：* 布林带缩口，但最新价格受压于布林带中轨，甚至开始跌破下轨。
  - *动能：* 近期出现“放量下跌、缩量反弹”；MACD 在零轴下方呈现死叉发散。

**【API 接口设计要求】** 提供以下两个 RESTful API：

1. `/api/scan`：执行A股主板全市场扫描，返回包含 `{code, name, price, signal_type(看涨/看跌)}` 的 JSON 列表。
2. `/api/kline?code=xxxx`：接收股票代码，返回该股票近 150 天的数据。JSON 结构必须符合前端图表要求：包含 time (yyyy-mm-dd), open, high, low, close, volume，以及计算好的 ma20, ma50, upper_band, middle_band, lower_band, macd_dif, macd_dea, macd_hist。

**【前端 UI 与图表设计要求（Lightweight Charts）】**

1. **页面布局：** 上半部分为扫盘结果表格，下半部分为 K 线图表区。
2. **图表实例化要求：**
   - **主图 (Main Chart)：** 绘制 Candlestick 蜡烛图。添加两条 Line Series 分别作为 MA20 和 MA50。添加布林带（可以通过上轨线、下轨线，并结合图表的 fill area 特性，或仅画出上下轨线）。
   - **副图 (Sub Chart - MACD)：** 在主图下方同步创建一个副图，显示 MACD 指标。DIF 和 DEA 使用 Line Series，Histogram 使用 Histogram Series（正数为红，负数为绿）。
   - **图表联动：** 主图和副图的十字光标 (Crosshair) 和时间轴缩放 (Time Scale) 必须同步联动。

**【你的输出任务】** 请一次性为我提供这个项目的核心代码（MVp版本），包含以下三部分：

1. **后端 Python 代码 (`main.py`)：** 包含 FastAPI 路由、AkShare 数据拉取与并发处理、pandas-ta 指标计算和看涨看跌逻辑过滤。
2. **前端页面与逻辑 (`App.jsx` 或 `App.vue`)：** 包含表格列表的渲染，以及点击行后调用 API 并触发图表渲染的逻辑。
3. **前端图表组件 (`ChartComponent.jsx` 或 `ChartComponent.vue`)：** 完整封装 `lightweight-charts` 的初始化、主副图配置、数据注入和联动同步逻辑