import { useEffect, useState } from 'react'

const MOMENTUM_DEFAULTS = {
  bull_enabled: true,
  bear_enabled: true,
  trend_enabled: true,
  squeeze_enabled: true,
  price_enabled: true,
  volume_enabled: true,
  macd_enabled: true,
  bb_low_quantile: 0.50,
  bull_trend_ratio: 0.55,
  bear_trend_ratio: 0.45,
  price_above_mid_tolerance: 0.98,
  bull_volume_ratio: 0.90,
  macd_zero_tolerance: 0.03,
  bear_volume_ratio: 0.95,
}

const HMM_DEFAULTS = {
  bullish_alignment_enabled: true,
  bullish_alignment_weight: 2.5,
  boll_breakout_enabled: true,
  boll_breakout_weight: 3.0,
  macd_cross_enabled: true,
  macd_cross_weight: 2.0,
  volume_burst_enabled: true,
  volume_burst_weight: 2.5,
  volume_burst_multiplier: 1.5,
  mf_bottom_cluster_enabled: true,
  mf_bottom_cluster_weight: 3.5,
  mf_bottom_cluster_threshold: 20.0,
  score_threshold: 7.5,
  skip_regime_check: false,
}

export const DEFAULTS = { momentum: MOMENTUM_DEFAULTS, hmm: HMM_DEFAULTS }

export function loadConfig(mode) {
  const defaults = DEFAULTS[mode]
  try {
    const saved = localStorage.getItem(`scanConfig.${mode}`)
    if (!saved) return { ...defaults }
    const obj = JSON.parse(saved)
    return { ...defaults, ...obj }
  } catch {
    return { ...defaults }
  }
}

export function saveConfig(mode, cfg) {
  try { localStorage.setItem(`scanConfig.${mode}`, JSON.stringify(cfg)) } catch {}
}

function Row({ label, hint, children }) {
  return (
    <div className="cfg-row">
      <div className="cfg-label">
        <span>{label}</span>
        {hint && <span className="cfg-hint">{hint}</span>}
      </div>
      <div className="cfg-control">{children}</div>
    </div>
  )
}

function Toggle({ checked, onChange, label }) {
  return (
    <label className="cfg-toggle">
      <input type="checkbox" checked={checked} onChange={e => onChange(e.target.checked)} />
      <span>{label}</span>
    </label>
  )
}

function NumInput({ value, onChange, step = 0.01, min, max }) {
  return (
    <input
      type="number"
      className="cfg-num"
      value={value}
      step={step}
      min={min}
      max={max}
      onChange={e => {
        const v = e.target.value
        if (v === '') return onChange(0)
        const n = Number(v)
        if (!Number.isNaN(n)) onChange(n)
      }}
    />
  )
}

export default function SettingsPanel({ mode, config, onChange, onClose, onReset }) {
  const set = (key, value) => onChange({ ...config, [key]: value })

  return (
    <div className="cfg-drawer">
      <div className="cfg-head">
        <b>⚙️ {mode === 'momentum' ? '动能扫盘参数' : 'HMM 选股参数'}</b>
        <div className="cfg-head-actions">
          <button className="cfg-reset" onClick={onReset}>恢复默认</button>
          <button className="cfg-close" onClick={onClose}>✕</button>
        </div>
      </div>
      <div className="cfg-body">
        {mode === 'momentum' ? (
          <>
            <div className="cfg-section">模型开关</div>
            <Row label="看涨模型">
              <Toggle checked={config.bull_enabled} onChange={v => set('bull_enabled', v)} label="启用" />
            </Row>
            <Row label="看跌模型">
              <Toggle checked={config.bear_enabled} onChange={v => set('bear_enabled', v)} label="启用" />
            </Row>

            <div className="cfg-section">条件开关</div>
            <Row label="趋势过滤" hint="MA20/MA50 多空占比">
              <Toggle checked={config.trend_enabled} onChange={v => set('trend_enabled', v)} label="启用" />
            </Row>
            <Row label="布林缩口" hint="近120日带宽分位">
              <Toggle checked={config.squeeze_enabled} onChange={v => set('squeeze_enabled', v)} label="启用" />
            </Row>
            <Row label="价格位置" hint="相对 BOLL 中轨">
              <Toggle checked={config.price_enabled} onChange={v => set('price_enabled', v)} label="启用" />
            </Row>
            <Row label="量能配合">
              <Toggle checked={config.volume_enabled} onChange={v => set('volume_enabled', v)} label="启用" />
            </Row>
            <Row label="MACD">
              <Toggle checked={config.macd_enabled} onChange={v => set('macd_enabled', v)} label="启用" />
            </Row>

            <div className="cfg-section">阈值参数</div>
            <Row label="布林缩口分位" hint="0-1，越小越严">
              <NumInput value={config.bb_low_quantile} onChange={v => set('bb_low_quantile', v)} step={0.05} min={0.05} max={0.95} />
            </Row>
            <Row label="看涨趋势占比" hint="MA20>MA50 天数占比">
              <NumInput value={config.bull_trend_ratio} onChange={v => set('bull_trend_ratio', v)} step={0.05} min={0.1} max={1.0} />
            </Row>
            <Row label="看跌趋势占比" hint="MA20>MA50 天数低于此">
              <NumInput value={config.bear_trend_ratio} onChange={v => set('bear_trend_ratio', v)} step={0.05} min={0.1} max={1.0} />
            </Row>
            <Row label="价格/中轨容差" hint="看涨: close≥mid×此值">
              <NumInput value={config.price_above_mid_tolerance} onChange={v => set('price_above_mid_tolerance', v)} step={0.01} min={0.8} max={1.1} />
            </Row>
            <Row label="看涨量比" hint="上涨量/下跌量 ≥ 此值">
              <NumInput value={config.bull_volume_ratio} onChange={v => set('bull_volume_ratio', v)} step={0.05} min={0.1} max={3.0} />
            </Row>
            <Row label="MACD 零轴容差" hint="|DIF|≤close×此值">
              <NumInput value={config.macd_zero_tolerance} onChange={v => set('macd_zero_tolerance', v)} step={0.005} min={0.001} max={0.2} />
            </Row>
            <Row label="看跌量比" hint="下跌均量/上涨均量 ≥ 此值">
              <NumInput value={config.bear_volume_ratio} onChange={v => set('bear_volume_ratio', v)} step={0.05} min={0.1} max={3.0} />
            </Row>
          </>
        ) : (
          <>
            <div className="cfg-section">市场择时</div>
            <Row label="忽略 HMM 熊市停止" hint="熊市也继续选股">
              <Toggle checked={config.skip_regime_check} onChange={v => set('skip_regime_check', v)} label="启用" />
            </Row>

            <div className="cfg-section">打分因子</div>
            <Row label="均线多头">
              <Toggle checked={config.bullish_alignment_enabled} onChange={v => set('bullish_alignment_enabled', v)} label="启用" />
              <NumInput value={config.bullish_alignment_weight} onChange={v => set('bullish_alignment_weight', v)} step={0.5} min={0} max={10} />
            </Row>
            <Row label="BOLL 突破">
              <Toggle checked={config.boll_breakout_enabled} onChange={v => set('boll_breakout_enabled', v)} label="启用" />
              <NumInput value={config.boll_breakout_weight} onChange={v => set('boll_breakout_weight', v)} step={0.5} min={0} max={10} />
            </Row>
            <Row label="MACD 金叉">
              <Toggle checked={config.macd_cross_enabled} onChange={v => set('macd_cross_enabled', v)} label="启用" />
              <NumInput value={config.macd_cross_weight} onChange={v => set('macd_cross_weight', v)} step={0.5} min={0} max={10} />
            </Row>
            <Row label="量能爆发">
              <Toggle checked={config.volume_burst_enabled} onChange={v => set('volume_burst_enabled', v)} label="启用" />
              <NumInput value={config.volume_burst_weight} onChange={v => set('volume_burst_weight', v)} step={0.5} min={0} max={10} />
            </Row>
            <Row label="MF 底部三线共振" hint="inter/near/mom 同时 ≤ 阈值">
              <Toggle checked={config.mf_bottom_cluster_enabled} onChange={v => set('mf_bottom_cluster_enabled', v)} label="启用" />
              <NumInput value={config.mf_bottom_cluster_weight} onChange={v => set('mf_bottom_cluster_weight', v)} step={0.5} min={0} max={10} />
            </Row>

            <div className="cfg-section">阈值参数</div>
            <Row label="放量倍数" hint="量 ≥ MA5量 × 此值">
              <NumInput value={config.volume_burst_multiplier} onChange={v => set('volume_burst_multiplier', v)} step={0.1} min={1.0} max={5.0} />
            </Row>
            <Row label="MF 底部阈值" hint="三条线均 ≤ 此值算共振">
              <NumInput value={config.mf_bottom_cluster_threshold} onChange={v => set('mf_bottom_cluster_threshold', v)} step={1} min={5} max={50} />
            </Row>
            <Row label="入选评分阈值" hint="综合评分 ≥ 此值">
              <NumInput value={config.score_threshold} onChange={v => set('score_threshold', v)} step={0.5} min={0} max={20} />
            </Row>
          </>
        )}
      </div>
    </div>
  )
}
