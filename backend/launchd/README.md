# launchd 定时任务

四个 LaunchAgent 分别在 A 股 / 港股 / 美股 / 主题股收盘后 30~35 分钟刷新缓存并重跑两种扫描,
结果落盘到 `cache/results/*_{market}.json`, 前端首屏直接读取.

## 安装

```bash
cd /Users/robin/Documents/Stocks_Scan/backend

# 1. 确保日志与缓存目录存在
mkdir -p logs cache/results cache/a cache/hk cache/us

# 2. 确保 .venv 已装好依赖
.venv/bin/pip install -r requirements.txt

# 3. 把 plist 安装到 LaunchAgents 并加载
for m in a hk us themes; do
  cp launchd/com.stocks_scan.warm.$m.plist ~/Library/LaunchAgents/
  launchctl unload ~/Library/LaunchAgents/com.stocks_scan.warm.$m.plist 2>/dev/null
  launchctl load ~/Library/LaunchAgents/com.stocks_scan.warm.$m.plist
done

# 4. 查看状态
launchctl list | grep stocks_scan
```

## 调度时间 (系统本地时区)

假设系统时区为 CEST/CET (GMT+2 / GMT+1):

| 市场 | Plist | 本地时间 | 对应收盘 |
|------|-------|----------|----------|
| A 股 | `com.stocks_scan.warm.a` | 09:30 | 15:00 CST + 30min |
| 港股 | `com.stocks_scan.warm.hk` | 10:30 | 16:00 HKT + 30min |
| 美股 | `com.stocks_scan.warm.us` | 22:30 | 16:00 ET + 30min |
| 主题股 | `com.stocks_scan.warm.themes` | 22:35 | 与 US 同(主题全为美股) |

如果你的系统时区不是欧洲, 请编辑每个 plist 的 `StartCalendarInterval`
把 `Hour` 改成对应收盘时间 + 30min 的本地时刻, 然后重新 `launchctl load`.

## 手动触发 (测试用)

```bash
launchctl start com.stocks_scan.warm.a
launchctl start com.stocks_scan.warm.hk
launchctl start com.stocks_scan.warm.us
launchctl start com.stocks_scan.warm.themes

# 或直接跑:
.venv/bin/python warm.py --market a
.venv/bin/python warm.py --market all
```

## 日志

`backend/logs/warm.{a,hk,us,themes}.{out,err}.log` — 每日追加.

## 卸载

```bash
for m in a hk us themes; do
  launchctl unload ~/Library/LaunchAgents/com.stocks_scan.warm.$m.plist
  rm ~/Library/LaunchAgents/com.stocks_scan.warm.$m.plist
done
```
