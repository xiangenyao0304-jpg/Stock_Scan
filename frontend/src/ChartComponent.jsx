import { useEffect, useRef } from 'react'
import { createChart, CrosshairMode, LineStyle } from 'lightweight-charts'

const DARK = {
  layout: { background: { color: '#161b22' }, textColor: '#c9d1d9' },
  grid:   { vertLines: { color: '#21262d' }, horzLines: { color: '#21262d' } },
  border: '#30363d',
}
const LIGHT = {
  layout: { background: { color: '#ffffff' }, textColor: '#1f2937' },
  grid:   { vertLines: { color: '#f1f5f9' }, horzLines: { color: '#f1f5f9' } },
  border: '#e5e7eb',
}

export default function ChartComponent({ data, divergences = [], theme = 'dark' }) {
  const mainRef = useRef(null)
  const midRef = useRef(null)
  const subRef = useRef(null)

  const chartsRef = useRef({})
  const seriesRef = useRef({})
  const syncingRef = useRef(false)

  // 创建图表（一次）
  useEffect(() => {
    if (!mainRef.current || !midRef.current || !subRef.current) return

    const palette = theme === 'light' ? LIGHT : DARK
    const commonOpts = {
      layout: palette.layout,
      grid: palette.grid,
      rightPriceScale: { borderColor: palette.border },
      timeScale: { borderColor: palette.border, timeVisible: true },
      crosshair: { mode: CrosshairMode.Normal },
      autoSize: true,
    }

    const mainChart = createChart(mainRef.current, {
      ...commonOpts,
      rightPriceScale: { borderColor: palette.border, scaleMargins: { top: 0.05, bottom: 0.25 } },
    })
    const midChart = createChart(midRef.current, commonOpts)
    const subChart = createChart(subRef.current, commonOpts)

    // --- 主图系列 ---
    const candle = mainChart.addCandlestickSeries({
      upColor: '#ef4444', downColor: '#22c55e',
      wickUpColor: '#ef4444', wickDownColor: '#22c55e',
      borderVisible: false,
    })
    const ma5 = mainChart.addLineSeries({
      color: '#e879f9', lineWidth: 1, priceLineVisible: false,
      lastValueVisible: false, title: 'MA5',
    })
    const ma20 = mainChart.addLineSeries({
      color: '#facc15', lineWidth: 1.5, priceLineVisible: false,
      lastValueVisible: false, title: 'MA20',
    })
    const ma50 = mainChart.addLineSeries({
      color: '#a78bfa', lineWidth: 1.5, priceLineVisible: false,
      lastValueVisible: false, title: 'MA50',
    })
    const ma200 = mainChart.addLineSeries({
      color: '#f97316', lineWidth: 2, priceLineVisible: false,
      lastValueVisible: false, title: 'MA200',
    })
    const upper = mainChart.addLineSeries({
      color: '#38bdf8', lineWidth: 2, lineStyle: LineStyle.Dashed,
      priceLineVisible: false, lastValueVisible: false, title: 'BOLL↑',
    })
    const middle = mainChart.addLineSeries({
      color: '#38bdf8', lineWidth: 1, lineStyle: LineStyle.Dotted,
      priceLineVisible: false, lastValueVisible: false, title: 'BOLL·',
    })
    const lower = mainChart.addLineSeries({
      color: '#38bdf8', lineWidth: 2, lineStyle: LineStyle.Dashed,
      priceLineVisible: false, lastValueVisible: false, title: 'BOLL↓',
    })
    const volume = mainChart.addHistogramSeries({
      priceFormat: { type: 'volume' },
      priceScaleId: 'vol',
      priceLineVisible: false,
      lastValueVisible: false,
      title: 'VOL',
    })
    mainChart.priceScale('vol').applyOptions({ scaleMargins: { top: 0.78, bottom: 0 } })

    // --- 副图 1: Market Forecast Cluster KR ---
    // cluster 背景柱 (最底层先加, 会被其他系列覆盖但仍显色)
    const clusterBg = midChart.addHistogramSeries({
      priceLineVisible: false, lastValueVisible: false, title: '',
      priceScaleId: 'cluster_bg',
      color: 'rgba(0,0,0,0)',
    })
    midChart.priceScale('cluster_bg').applyOptions({ scaleMargins: { top: 0, bottom: 0 }, visible: false })
    const smfInter = midChart.addLineSeries({
      color: '#16a34a', lineWidth: 2.5,
      priceLineVisible: false, lastValueVisible: false, title: '中期',
    })
    const smfShort = midChart.addLineSeries({
      color: '#3b82f6', lineWidth: 1.8,
      priceLineVisible: false, lastValueVisible: false, title: '短期',
    })
    const smfMomentum = midChart.addLineSeries({
      color: '#ef4444', lineWidth: 1.6,
      priceLineVisible: false, lastValueVisible: false, title: '动能',
    })
    const refColor = theme === 'light' ? '#9ca3af' : '#6b7280'
    smfInter.createPriceLine({
      price: 80, color: refColor, lineWidth: 1,
      lineStyle: LineStyle.Dotted, axisLabelVisible: true, title: '80',
    })
    smfInter.createPriceLine({
      price: 20, color: refColor, lineWidth: 1,
      lineStyle: LineStyle.Dotted, axisLabelVisible: true, title: '20',
    })

    // --- 背离连线 (画在 smf_short 同副图上) ---
    const bullDiv = midChart.addLineSeries({
      color: '#facc15', lineWidth: 2, lineStyle: LineStyle.Solid,
      priceLineVisible: false, lastValueVisible: false, title: '牛背离',
      crosshairMarkerVisible: false,
    })
    const bearDiv = midChart.addLineSeries({
      color: '#d946ef', lineWidth: 2, lineStyle: LineStyle.Solid,
      priceLineVisible: false, lastValueVisible: false, title: '熊背离',
      crosshairMarkerVisible: false,
    })

    // --- 副图 2: MACD ---
    const macdHist = subChart.addHistogramSeries({
      priceLineVisible: false, lastValueVisible: false, title: 'MACD',
    })
    const macdDif = subChart.addLineSeries({
      color: '#60a5fa', lineWidth: 1.5,
      priceLineVisible: false, lastValueVisible: false, title: 'DIF',
    })
    const macdDea = subChart.addLineSeries({
      color: '#f97316', lineWidth: 1.5,
      priceLineVisible: false, lastValueVisible: false, title: 'DEA',
    })
    macdDif.createPriceLine({
      price: 0, color: refColor, lineWidth: 1,
      lineStyle: LineStyle.Dotted, axisLabelVisible: false, title: '',
    })

    chartsRef.current = { mainChart, midChart, subChart }
    seriesRef.current = {
      candle, ma5, ma20, ma50, ma200, upper, middle, lower, volume,
      clusterBg, smfInter, smfShort, smfMomentum, bullDiv, bearDiv,
      macdHist, macdDif, macdDea,
    }

    // --- 三图时间轴同步 ---
    const charts = [mainChart, midChart, subChart]
    const unsubs = []
    const syncTime = (src) => (range) => {
      if (!range || syncingRef.current) return
      syncingRef.current = true
      charts.forEach(c => { if (c !== src) c.timeScale().setVisibleLogicalRange(range) })
      syncingRef.current = false
    }
    charts.forEach(c => {
      const fn = syncTime(c)
      c.timeScale().subscribeVisibleLogicalRangeChange(fn)
      unsubs.push(() => c.timeScale().unsubscribeVisibleLogicalRangeChange(fn))
    })

    // --- 十字光标同步 ---
    const anchorFor = (c) => {
      if (c === midChart) return seriesRef.current.smfInter
      if (c === subChart) return seriesRef.current.macdDif
      return seriesRef.current.candle
    }
    const syncCrosshair = (src) => (param) => {
      if (!param || !param.time) {
        charts.forEach(c => { if (c !== src) c.clearCrosshairPosition() })
        return
      }
      charts.forEach(c => {
        if (c !== src) c.setCrosshairPosition(NaN, param.time, anchorFor(c))
      })
    }
    charts.forEach(c => {
      const fn = syncCrosshair(c)
      c.subscribeCrosshairMove(fn)
      unsubs.push(() => c.unsubscribeCrosshairMove(fn))
    })

    return () => {
      unsubs.forEach(u => { try { u() } catch {} })
      charts.forEach(c => c.remove())
      chartsRef.current = {}
      seriesRef.current = {}
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [theme])

  // 数据注入
  useEffect(() => {
    if (!data || !seriesRef.current.candle) return
    const s = seriesRef.current

    const candleData = data.map(d => ({
      time: d.time, open: d.open, high: d.high, low: d.low, close: d.close,
    }))
    const pickLine = key => data
      .filter(d => d[key] !== null && d[key] !== undefined)
      .map(d => ({ time: d.time, value: d[key] }))

    s.candle.setData(candleData)
    s.ma5.setData(pickLine('ma5'))
    s.ma20.setData(pickLine('ma20'))
    s.ma50.setData(pickLine('ma50'))
    s.ma200.setData(pickLine('ma200'))
    s.upper.setData(pickLine('upper_band'))
    s.middle.setData(pickLine('middle_band'))
    s.lower.setData(pickLine('lower_band'))

    s.volume.setData(
      data.map(d => ({
        time: d.time,
        value: d.volume,
        color: d.close >= d.open
          ? 'rgba(239, 68, 68, 0.5)'
          : 'rgba(34, 197, 94, 0.5)',
      }))
    )

    // Cluster 背景色 (满分 100, 仅 cluster 期高亮填充)
    s.clusterBg.setData(
      data.map(d => {
        const color = d.mf_bull_cluster
          ? 'rgba(34, 197, 94, 0.18)'
          : d.mf_bear_cluster
            ? 'rgba(239, 68, 68, 0.18)'
            : 'rgba(0,0,0,0)'
        return { time: d.time, value: 100, color }
      })
    )

    s.smfInter.setData(pickLine('smf_intermediate'))
    s.smfShort.setData(pickLine('smf_short'))
    s.smfMomentum.setData(pickLine('smf_momentum'))

    // Confirm 圆点 (牛绿 / 熊红) 挂在 smf_short 上
    const markers = []
    data.forEach(d => {
      if (d.mf_bull_confirm) {
        markers.push({
          time: d.time, position: 'belowBar',
          color: '#22c55e', shape: 'circle', text: '▲',
        })
      }
      if (d.mf_bear_confirm) {
        markers.push({
          time: d.time, position: 'aboveBar',
          color: '#ef4444', shape: 'circle', text: '▼',
        })
      }
    })
    s.smfShort.setMarkers(markers)

    // 背离连线 (牛/熊 各画最近一次, 两点连线)
    const bullDivPoints = []
    const bearDivPoints = []
    ;(divergences || []).forEach(dv => {
      const from = { time: dv.from_time, value: dv.from_value }
      const to = { time: dv.to_time, value: dv.to_value }
      if (dv.kind === 'bull') {
        bullDivPoints.push(from, to)
      } else if (dv.kind === 'bear') {
        bearDivPoints.push(from, to)
      }
    })
    // lightweight-charts 的 line series 按时间升序
    const sortByTime = (a, b) => a.time.localeCompare(b.time)
    s.bullDiv.setData(bullDivPoints.sort(sortByTime))
    s.bearDiv.setData(bearDivPoints.sort(sortByTime))

    s.macdDif.setData(pickLine('macd_dif'))
    s.macdDea.setData(pickLine('macd_dea'))
    s.macdHist.setData(
      data
        .filter(d => d.macd_hist !== null && d.macd_hist !== undefined)
        .map(d => ({
          time: d.time,
          value: d.macd_hist,
          color: d.macd_hist >= 0 ? '#ef4444' : '#22c55e',
        }))
    )

    chartsRef.current.mainChart?.timeScale().fitContent()
    chartsRef.current.midChart?.timeScale().fitContent()
    chartsRef.current.subChart?.timeScale().fitContent()
  }, [data, divergences])

  const labelColor = theme === 'light' ? '#6b7280' : '#8b949e'
  const labelBg = theme === 'light' ? '#f3f4f6' : '#0d1117'
  const labelStyle = {
    borderTop: `1px solid ${theme === 'light' ? '#e5e7eb' : '#30363d'}`,
    padding: '2px 10px',
    fontSize: 12,
    color: labelColor,
    background: labelBg,
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div ref={mainRef} style={{ flex: '1 1 55%', minHeight: 0 }} />
      <div style={labelStyle}>
        Market Forecast Cluster KR ·
        <span style={{color:'#16a34a', fontWeight:600}}> 中期</span> ·
        <span style={{color:'#3b82f6'}}> 短期</span> ·
        <span style={{color:'#ef4444'}}> 动能</span> ·
        <span style={{color:'#22c55e'}}> 底共振</span>/<span style={{color:'#ef4444'}}>顶共振</span> ·
        <span style={{color:'#facc15'}}> 牛背离</span>/<span style={{color:'#d946ef'}}>熊背离</span>
      </div>
      <div ref={midRef} style={{ flex: '1 1 22%', minHeight: 100 }} />
      <div style={labelStyle}>
        MACD (12, 26, 9) ·
        <span style={{color:'#60a5fa'}}> DIF</span> ·
        <span style={{color:'#f97316'}}> DEA</span>
      </div>
      <div ref={subRef} style={{ flex: '1 1 23%', minHeight: 100 }} />
    </div>
  )
}
