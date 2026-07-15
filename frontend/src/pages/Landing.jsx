import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { BASE, getQuotes, resolveQuery } from '../api'

const COMPANIES = [
  { t: 'AAPL', c: '#555b63' }, { t: 'NVDA', c: '#76b900' }, { t: 'GME', c: '#b5202e' },
  { t: 'MSFT', c: '#0078d4' }, { t: 'AMZN', c: '#ff9900' }, { t: 'SHOP', c: '#5e9c3a' },
  { t: 'TSLA', c: '#cc2b2b' }, { t: 'PLTR', c: '#3b4250' }, { t: 'GOOGL', c: '#ea4335' },
  { t: 'META', c: '#1877f2' }, { t: 'F', c: '#1a4fa0' }, { t: 'CROX', c: '#5fb234' },
  { t: 'BRK-B', c: '#2c4a6e' }, { t: 'DECK', c: '#b0455f' }, { t: 'WING', c: '#12805f' },
  { t: 'DAKT', c: '#e2662a' }, { t: 'JPM', c: '#123c5e' }, { t: 'UFPT', c: '#2c7fb8' },
  { t: 'CRVL', c: '#5b4b8a' },
]
const STEP = 360 / COMPANIES.length
const RADIUS = 478
// card display names that differ from the ticker (ticker still drives logo/quote/report)
const LABEL = { F: 'Ford' }

const TAPE = [
  ['AAPL', '+0.7%', 'up'], ['NVDA', '+2.1%', 'up'], ['MSFT', '+0.6%', 'up'],
  ['GOOGL', '+1.0%', 'up'], ['AMZN', '-0.4%', 'dn'], ['JPM', '-0.3%', 'dn'],
  ['TSLA', '+3.2%', 'up'], ['CROX', '+1.4%', 'up'], ['DAKT', '+0.8%', 'up'],
]

function Spark({ data, up }) {
  if (!data || data.length < 2) return null
  const w = 138, h = 30
  const lo = Math.min(...data), hi = Math.max(...data)
  const span = hi - lo || 1
  const step = w / (data.length - 1)
  const pts = data.map((v, i) => [i * step, h - ((v - lo) / span) * (h - 4) - 2])
  const line = pts.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(' ')
  const area = `0,${h} ${line} ${w},${h}`
  const stroke = up ? 'rgba(255,255,255,0.85)' : 'rgba(255,255,255,0.6)'
  return (
    <svg className="spark" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" aria-hidden>
      <polygon points={area} fill="rgba(255,255,255,0.14)" />
      <polyline points={line} fill="none" stroke={stroke} strokeWidth="1.6"
        strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  )
}

function SpiralCard({ c, i, quote, onClick }) {
  const [ok, setOk] = useState(true)
  const transform = `translate(-50%,-50%) rotateY(${i * STEP}deg) translateZ(${RADIUS}px)`
  const pct = quote?.pct
  const price = quote?.price
  const up = pct == null ? true : pct >= 0
  return (
    <div className="cc" style={{ '--c': c.c, transform }} onClick={onClick} title={c.t}>
      <Spark data={quote?.spark} up={up} />
      <div className="cc-in">
        <div className="cc-top">
          {ok
            ? <img className="lgi" src={`${BASE}/logo/${c.t}`} alt="" onError={() => setOk(false)} />
            : <span className="lgm">{c.t[0]}</span>}
          <span className="tk">{LABEL[c.t] || c.t}</span>
        </div>
        <div className="cc-bot">
          {price != null && <span className="pr">${price >= 1000 ? price.toFixed(0) : price.toFixed(2)}</span>}
          {pct != null && (
            <span className={`pc ${up ? 'u' : 'd'}`}>{up ? '▲' : '▼'} {Math.abs(pct).toFixed(1)}%</span>
          )}
        </div>
      </div>
    </div>
  )
}

export default function Landing() {
  const nav = useNavigate()
  const [q, setQ] = useState('')
  const [quotes, setQuotes] = useState(null)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  // tiles pass a known ticker -> go straight to the report
  const go = (t) => { const v = (t || '').trim().toUpperCase(); if (v) nav(`/report/${v}`) }
  // the search box accepts a ticker OR a company name -> resolve first
  const search = async (e) => {
    e.preventDefault()
    const query = q.trim()
    if (!query) return
    setErr(''); setBusy(true)
    try {
      const { ticker } = await resolveQuery(query)
      nav(`/report/${ticker}`)
    } catch {
      setErr(`No company or ticker matching "${query}"`)
      setBusy(false)
    }
  }

  useEffect(() => {
    let alive = true
    const load = () => getQuotes().then((d) => { if (alive) setQuotes(d) }).catch(() => {})
    load()
    const iv = setInterval(load, 30000)
    return () => { alive = false; clearInterval(iv) }
  }, [])

  // Auto-spin the oval; on hover it pauses and the wheel clicks it company-by-
  // company with a detent (snap) + a little pop, instead of scrubbing freely.
  const ovalRef = useRef(null)
  const ringRef = useRef(null)
  const angleRef = useRef(0)
  const targetRef = useRef(0)
  const accumRef = useRef(0)
  const hoverRef = useRef(false)
  useEffect(() => {
    const oval = ovalRef.current, ring = ringRef.current
    if (!oval || !ring) return
    const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    const AUTO = 360 / 46 / 1000            // deg per ms — matches the old 46s loop
    const NOTCH = 80                        // wheel travel per company "click"
    const apply = () => { ring.style.transform = `translate(-50%,-50%) rotateY(${angleRef.current}deg)` }
    let raf, last = performance.now()
    const tick = (now) => {
      const dt = now - last; last = now
      if (hoverRef.current) {
        const diff = targetRef.current - angleRef.current   // ease into the snapped slot
        if (Math.abs(diff) > 0.02) { angleRef.current += diff * Math.min(1, dt / 85); apply() }
      } else if (!reduce) {
        angleRef.current += AUTO * dt; apply()
      }
      raf = requestAnimationFrame(tick)
    }
    apply()
    raf = requestAnimationFrame(tick)
    const pop = () => {                     // brief tactile "tick" pulse
      oval.classList.remove('tickpulse'); void oval.offsetWidth; oval.classList.add('tickpulse')
    }
    const onWheel = (e) => {
      e.preventDefault()                    // click the oval instead of scrolling the page
      const d = Math.abs(e.deltaX) > Math.abs(e.deltaY) ? e.deltaX : e.deltaY
      accumRef.current += d
      let clicked = false
      while (Math.abs(accumRef.current) >= NOTCH) {   // one detent per NOTCH of travel
        const s = Math.sign(accumRef.current)
        targetRef.current -= s * STEP
        accumRef.current -= s * NOTCH
        clicked = true
      }
      if (clicked) pop()
    }
    const enter = () => {                    // snap to the nearest company when you grab it
      hoverRef.current = true
      targetRef.current = Math.round(angleRef.current / STEP) * STEP
      accumRef.current = 0
    }
    const leave = () => { hoverRef.current = false; last = performance.now() }
    oval.addEventListener('wheel', onWheel, { passive: false })
    oval.addEventListener('mouseenter', enter)
    oval.addEventListener('mouseleave', leave)
    return () => {
      cancelAnimationFrame(raf)
      oval.removeEventListener('wheel', onWheel)
      oval.removeEventListener('mouseenter', enter)
      oval.removeEventListener('mouseleave', leave)
    }
  }, [])

  const qOf = {}
  if (quotes) quotes.forEach((x) => { qOf[x.symbol] = x })
  const tape = (quotes && quotes.some((x) => x.pct != null))
    ? quotes.filter((x) => x.pct != null).map((x) => [x.symbol, `${x.pct >= 0 ? '+' : ''}${x.pct.toFixed(1)}%`, x.pct >= 0 ? 'up' : 'dn'])
    : TAPE
  const loop = [...tape, ...tape, ...tape, ...tape]

  return (
    <div className="page">
      <div className="aurora" aria-hidden="true" />
      <div className="intro">
        <span className="m">Verity<span className="dot">.</span></span>
        <span className="mt">equity research you can verify</span>
      </div>

      <div className="tape">
        <span className="tape-in">
          {loop.map(([t, c, d], i) => (
            <span key={i}>{t} <span className={d}>{c}</span></span>
          ))}
        </span>
      </div>

      <div className="top">
        <div className="wordmark">Verity<span className="dot">.</span></div>
        <div className="tagline">equity research you can verify</div>
        <p className="subhead">
          A bull and a bear debate any stock from its SEC filing. A verifier then
          checks every claim against the source, so nothing is made up.
        </p>
        <form className="search" onSubmit={search}>
          <input placeholder="Search a company or ticker, e.g. Apple" value={q}
            onChange={(e) => { setQ(e.target.value); if (err) setErr('') }} aria-label="company or ticker" />
          <button className="btn" type="submit" disabled={busy}>{busy ? 'Finding…' : 'Analyze'}</button>
        </form>
        {err && <div className="search-err">{err}</div>}
      </div>

      <div className="scene">
        <div className="oval-wrap">
          <div className="clicknote">Click any company to see its <span>latest verified breakdown</span></div>
          <div className="oval" ref={ovalRef}>
            <div className="ring" ref={ringRef}>
              {COMPANIES.map((c, i) => (
                <SpiralCard key={c.t} c={c} i={i} quote={qOf[c.t]} onClick={() => go(c.t)} />
              ))}
            </div>
          </div>
        </div>
      </div>

      <div className="bottom">
        <div className="how">
          <div><span className="n">1</span> pull the filing</div>
          <div><span className="n">2</span> bull vs bear</div>
          <div><span className="n">3</span> verify every claim</div>
        </div>
        <p className="tech-line">
          Verity is a multi-agent system on LangGraph: a bull and a bear agent draft
          opposing theses from the filing, then a verifier agent scores what is grounded.
        </p>
        <div className="badges">
          <span>LangGraph</span><span>Multi-agent</span><span>Claude Sonnet</span>
          <span>SEC EDGAR</span><span>Claim verification</span>
        </div>
        <div className="disc">Verity generates research for education, not investment advice.</div>
      </div>
    </div>
  )
}
