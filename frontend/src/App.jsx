import { useCallback, useEffect, useState } from 'react'
import ChartComponent from './ChartComponent.jsx'
import SettingsPanel, { DEFAULTS, loadConfig, saveConfig } from './SettingsPanel.jsx'

const MARKETS = [
  { key: 'a',      label: 'A 股' },
  { key: 'hk',     label: '港股 (恒生科技)' },
  { key: 'us',     label: '美股 (R1G)' },
  { key: 'themes', label: '主题股' },
]

const RAW_API_BASE = (import.meta.env.VITE_API_BASE || '').trim()
const API_BASE = RAW_API_BASE.replace(/\/+$/, '')
const THEMES_URL = new URL('themes.html', window.location.origin + import.meta.env.BASE_URL).toString()

function buildApiUrl(path, params = {}) {
  const pathname = path.startsWith('/') ? path : `/${path}`
  const base = API_BASE || window.location.origin
  const url = new URL(`${base}${pathname}`)
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      url.searchParams.set(key, value)
    }
  })
  return url.toString()
}

export default function App() {
  const [mode, setMode] = useState('momentum')
  const [market, setMarket] = useState(() => {
    const saved = typeof localStorage !== 'undefined' ? localStorage.getItem('market') : null
    return MARKETS.some(m => m.key === saved) ? saved : 'a'
  })
  const [theme, setTheme] = useState(() => {
    const saved = typeof localStorage !== 'undefined' ? localStorage.getItem('theme') : null
    if (saved === 'light' || saved === 'dark') return saved
    return 'dark'
  })

  const [momentumCfg, setMomentumCfg] = useState(() => loadConfig('momentum'))
  const [hmmCfg, setHmmCfg] = useState(() => loadConfig('hmm'))
  const [showSettings, setShowSettings] = useState(false)

  useEffect(() => {
    try { localStorage.setItem('market', market) } catch {}
  }, [market])

  useEffect(() => { saveConfig('momentum', momentumCfg) }, [momentumCfg])
  useEffect(() => { saveConfig('hmm', hmmCfg) }, [hmmCfg])

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
    try { localStorage.setItem('theme', theme) } catch {}
  }, [theme])

  const [list, setList] = useState([])
  const [loadingScan, setLoadingScan] = useState(false)
  const [scanError, setScanError] = useState('')

  const [hmmData, setHmmData] = useState(null)
  const [loadingHmm, setLoadingHmm] = useState(false)
  const [hmmError, setHmmError] = useState('')

  const [selected, setSelected] = useState(null)
  const [kline, setKline] = useState([])
  const [divergences, setDivergences] = useState([])
  const [loadingKline, setLoadingKline] = useState(false)
  const [klineError, setKlineError] = useState('')

  const runScan = useCallback(async () => {
    setLoadingScan(true)
    setScanError('')
    try {
      const res = await fetch(buildApiUrl('/api/scan', { market }), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(momentumCfg),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setList(data)
    } catch (err) {
      setScanError(err.message || '扫描失败')
    } finally {
      setLoadingScan(false)
    }
  }, [momentumCfg, market])

  const runHmmScan = useCallback(async () => {
    setLoadingHmm(true)
    setHmmError('')
    try {
      const res = await fetch(buildApiUrl('/api/hmm_scan', { market }), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(hmmCfg),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setHmmData(data)
    } catch (err) {
      setHmmError(err.message || 'HMM扫描失败')
    } finally {
      setLoadingHmm(false)
    }
  }, [hmmCfg, market])

  const selectStock = useCallback(async (item) => {
    setSelected(item)
    setLoadingKline(true)
    setKlineError('')
    try {
      const res = await fetch(buildApiUrl('/api/kline', { code: item.code, market }))
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      const bars = Array.isArray(data) ? data : (data.bars || [])
      const divs = Array.isArray(data) ? [] : (data.divergences || [])
      setKline(bars)
      setDivergences(divs)
    } catch (err) {
      setKlineError(err.message || 'K线加载失败')
      setKline([])
      setDivergences([])
    } finally {
      setLoadingKline(false)
    }
  }, [market])

  useEffect(() => { runScan() }, [runScan])

  useEffect(() => {
    setSelected(null)
    setKline([])
    setDivergences([])
    setHmmData(null)
  }, [market])

  const isMomentum = mode === 'momentum'
  const statusText = isMomentum
    ? (loadingScan
        ? '扫描中…'
        : scanError
          ? scanError
          : `命中 ${list.length} 只`)
    : (loadingHmm
        ? 'HMM扫描中（全量扫盘较慢，请耐心等待）…'
        : hmmError
          ? hmmError
          : hmmData
            ? `命中 ${hmmData.results.length} 只`
            : '尚未开始 HMM 扫描')

  return (
    <div className="app">
      <div className="grain" />
      <header className="masthead">
        <div className="masthead-main">
          <div className="eyebrow">Multi-Market Scanner</div>
          <h1 className="hero-title">
            Stocks <span className="hero-italic">Radar</span>
          </h1>
          <p className="hero-subtitle">
            多市场选股雷达，统一查看 A 股、港股、美股与主题池的动能扫描和 HMM 结果。
          </p>
        </div>
        <div className="masthead-side">
          <div className="side-label">Current Mode</div>
          <div className="side-value">{isMomentum ? 'Momentum Scan' : 'HMM Selection'}</div>
          <div className={`meta ${scanError || hmmError ? 'error' : ''}`}>{statusText}</div>
        </div>
      </header>

      <div className="control-shell">
        <div className="header">
          <div className="tabs markets">
            {MARKETS.map(m => (
              <button
                key={m.key}
                className={market === m.key ? 'tab active' : 'tab'}
                onClick={() => setMarket(m.key)}
              >{m.label}</button>
            ))}
          </div>
          <div className="tabs">
            <button
              className={isMomentum ? 'tab active' : 'tab'}
              onClick={() => setMode('momentum')}
            >动能扫盘</button>
            <button
              className={!isMomentum ? 'tab active' : 'tab'}
              onClick={() => setMode('hmm')}
            >HMM选股</button>
          </div>
          <a
            className="theme-toggle"
            href={THEMES_URL}
            target="_blank"
            rel="noreferrer"
            title="主题投资名单"
          >
            主题子页
          </a>
          <button
            className="theme-toggle"
            onClick={() => setShowSettings(s => !s)}
            title="参数设置"
          >
            参数
          </button>
          <button
            className="theme-toggle"
            onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
            title="切换主题"
          >
            {theme === 'dark' ? '浅色版' : '深色版'}
          </button>
          <button
            className="primary"
            onClick={isMomentum ? runScan : runHmmScan}
            disabled={isMomentum ? loadingScan : loadingHmm}
          >
            {isMomentum
              ? (loadingScan ? '扫描中…' : '重新扫描')
              : (loadingHmm ? 'HMM扫描中…' : (hmmData ? '重新扫描' : 'HMM扫描'))}
          </button>
        </div>
      </div>

      {showSettings && (
        <SettingsPanel
          mode={mode}
          config={isMomentum ? momentumCfg : hmmCfg}
          onChange={cfg => (isMomentum ? setMomentumCfg(cfg) : setHmmCfg(cfg))}
          onClose={() => setShowSettings(false)}
          onReset={() => (isMomentum
            ? setMomentumCfg({ ...DEFAULTS.momentum })
            : setHmmCfg({ ...DEFAULTS.hmm }))}
        />
      )}

      {!isMomentum && hmmData && (
        <div className={`regime-bar regime-${hmmData.regime.state}`}>
          <span>📅 {hmmData.date}</span>
          <span>🚦 HMM判定：<b>{hmmData.regime.label}</b></span>
          <span className="prob">
            概率：熊 {(hmmData.regime.probabilities[0] * 100).toFixed(1)}%
            · 震 {(hmmData.regime.probabilities[1] * 100).toFixed(1)}%
            · 牛 {(hmmData.regime.probabilities[2] * 100).toFixed(1)}%
          </span>
          {!hmmData.regime.proceed && (
            <span className="warn">⛔ 当前市场环境恶劣，停止交易</span>
          )}
        </div>
      )}

      <div className="panels">
        <div className="table-wrap">
          {isMomentum ? (
            <table>
              <thead>
                <tr>
                  <th style={{width: 90}}>代码</th>
                  <th>名称</th>
                  <th style={{width: 90}}>最新价</th>
                  <th style={{width: 90}}>信号</th>
                </tr>
              </thead>
              <tbody>
                {list.length === 0 && !loadingScan && (
                  <tr><td colSpan="4" style={{textAlign:'center', padding: 24, color:'#6e7681'}}>
                    暂无命中，试试点击"重新扫描"
                  </td></tr>
                )}
                {list.map(item => (
                  <tr
                    key={item.code}
                    className={selected?.code === item.code ? 'active' : ''}
                    onClick={() => selectStock(item)}
                  >
                    <td>{item.code}</td>
                    <td>{item.name}</td>
                    <td>{item.price.toFixed(2)}</td>
                    <td>
                      <span className={'tag ' + (item.signal_type === '看涨' ? 'bull' : 'bear')}>
                        {item.signal_type}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <table>
              <thead>
                <tr>
                  <th style={{width: 40}}>#</th>
                  <th style={{width: 90}}>代码</th>
                  <th style={{width: 120}}>名称</th>
                  <th style={{width: 70}}>评分</th>
                  <th>触发信号</th>
                </tr>
              </thead>
              <tbody>
                {(!hmmData || hmmData.results.length === 0) && !loadingHmm && (
                  <tr><td colSpan="5" style={{textAlign:'center', padding: 24, color:'#6e7681'}}>
                    {hmmData && !hmmData.regime.proceed
                      ? '市场状态为熊市，已停止选股'
                      : hmmData
                        ? '本日无符合条件（评分 ≥ 7.5）的个股'
                        : '点击右上角 "HMM扫描" 开始（首次拉取全量，可能数分钟）'}
                  </td></tr>
                )}
                {hmmData && hmmData.results.map((item, idx) => (
                  <tr
                    key={item.code}
                    className={selected?.code === item.code ? 'active' : ''}
                    onClick={() => selectStock({
                      code: item.code,
                      name: item.name,
                      signal_type: `HMM·${item.score.toFixed(1)}`,
                    })}
                  >
                    <td>{idx + 1}</td>
                    <td>{item.code}</td>
                    <td>{item.name}</td>
                    <td><b style={{color: '#58a6ff'}}>{item.score.toFixed(1)}</b></td>
                    <td>
                      {item.signals.map(s => (
                        <span key={s} className="tag-mini">{s}</span>
                      ))}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div className="chart-wrap">
          <div className="chart-head">
            {selected
              ? <>📈 {selected.code} {selected.name} &nbsp;·&nbsp; <span>{selected.signal_type}</span></>
              : '请在上方列表选择一只股票查看 K 线'}
            {loadingKline && <span className="loading"> · 加载中…</span>}
            {klineError && <span className="error"> · {klineError}</span>}
          </div>
          <div className="chart-body">
            {kline.length > 0
              ? <ChartComponent data={kline} divergences={divergences} theme={theme} />
              : <div className="empty">{selected ? '暂无数据' : '👉 点击列表中的股票开始'}</div>}
          </div>
        </div>
      </div>
    </div>
  )
}
