import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import ReactMarkdown from 'react-markdown'
import { BASE } from '../api'

const STEPS = ['fetch', 'bull', 'bear', 'verify', 'compose']
const STEP_LABEL = { fetch: 'read filing', bull: 'bull case', bear: 'bear case', verify: 'verify claims', compose: 'compose' }

function scoreColor(s) {
  if (s == null) return 'var(--text-muted)'
  if (s >= 85) return 'var(--up)'
  if (s >= 70) return 'var(--amber)'
  return 'var(--down)'
}

// a faint rising market line sweeping across the bottom — cleaner than candles
const MKT_LINE = 'M0,232 C90,224 140,196 220,202 S360,150 440,164 S590,108 670,120 S820,58 900,78 S1000,50 1000,50'

// render the verifier report, bolding all-caps sideheadings like "SCORE:" / "FEEDBACK:"
function VerifyBody({ text }) {
  return (
    <pre>
      {(text || '').split('\n').map((line, i) => {
        const m = line.match(/^([A-Z][A-Z0-9 /()&'-]*:)(.*)$/)
        return (
          <span key={i}>
            {m ? <><strong>{m[1]}</strong>{m[2]}</> : line}
            {'\n'}
          </span>
        )
      })}
    </pre>
  )
}

function Figures() {
  return (
    <div className="figures" aria-hidden="true">
      <svg className="mktline" viewBox="0 0 1000 260" preserveAspectRatio="none">
        <defs>
          <linearGradient id="mlg" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="rgba(45,212,191,0.15)" />
            <stop offset="1" stopColor="rgba(45,212,191,0)" />
          </linearGradient>
        </defs>
        <path d={`${MKT_LINE} L1000,260 L0,260 Z`} fill="url(#mlg)" />
        <path d={MKT_LINE} fill="none" stroke="rgba(45,212,191,0.30)" strokeWidth="2.5" />
      </svg>
    </div>
  )
}

export default function Report() {
  const { ticker } = useParams()
  const nav = useNavigate()
  const [data, setData] = useState(null)
  const [err, setErr] = useState(null)
  const [step, setStep] = useState(0)
  const [logoOk, setLogoOk] = useState(true)

  useEffect(() => {
    setData(null); setErr(null); setStep(0); setLogoOk(true)
    const idxOf = { fetch: 0, bull: 1, bear: 2, verify: 3, spin: 3, compose: 4 }
    let done = false
    const es = new EventSource(`${BASE}/analyze/stream?ticker=${encodeURIComponent(ticker)}`)
    es.onmessage = (ev) => {
      const msg = JSON.parse(ev.data)
      if (msg.step != null && idxOf[msg.step] != null) {
        setStep((s) => Math.max(s, idxOf[msg.step]))
      } else if (msg.done) {
        done = true; setStep(STEPS.length - 1); setData(msg.result); es.close()
      } else if (msg.error) {
        done = true; setErr(msg.error); es.close()
      }
    }
    es.onerror = () => { if (!done) setErr('Connection lost. Is the API running?'); es.close() }
    return () => es.close()
  }, [ticker])

  const download = () => {
    const blob = new Blob([data.memo], { type: 'text/markdown' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url; a.download = `${data.ticker}_memo.md`; a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className={`rpage${!data && !err ? ' loading-state' : ''}`}>
      <div className="aurora" aria-hidden="true" />
      <Figures />

      <div className="wrap rwrap">
        <div className="rnav">
          <span className="rback" onClick={() => nav('/')}>&larr; Verity</span>
          <span className="mono rtick">{ticker}</span>
        </div>

        {!data && !err && (
          <div className="loading">
            <div className="lbrand">
              <div className="wordmark">Verity<span className="dot">.</span></div>
            </div>
            <div className="pipe big">
              {STEPS.map((s, i) => (
                <span key={s} className="pcell">
                  <span className={`pstep ${i < step ? 'done' : i === step ? 'active' : ''}`}>
                    <span className="pd" />{STEP_LABEL[s]}
                  </span>
                  {i < STEPS.length - 1 && <span className="psep">&rsaquo;</span>}
                </span>
              ))}
            </div>
            <p className="ploud big">Reading {ticker}&rsquo;s filing and building a verified view. This takes about 20 to 40 seconds.</p>
          </div>
        )}

        {err && (
          <div className="loading">
            <div className="lbrand">
              <div className="wordmark">Verity<span className="dot">.</span></div>
            </div>
            <p style={{ color: 'var(--down)', fontSize: 16 }}>Couldn&rsquo;t analyze {ticker}.</p>
            <p style={{ color: 'var(--text-muted)', fontSize: 13, maxWidth: 460, textAlign: 'center' }}>{err}</p>
            <button className="btn btn-ghost" onClick={() => nav('/')}>Back to search</button>
          </div>
        )}

        {data && (
          <div className="result">
            <div className="rhead">
              <div className="company">
                {logoOk
                  ? <img className="clogo" src={`${BASE}/logo/${data.ticker}`} alt="" onError={() => setLogoOk(false)} />
                  : <span className="clogo-fb">{data.ticker[0]}</span>}
                <div>
                  <h1>{data.name}</h1>
                  <div className="meta">
                    {data.ticker} &middot; {data.form} filed {data.filing_date} &middot;{' '}
                    <a href={data.filing_url} target="_blank" rel="noreferrer" style={{ color: 'var(--accent)' }}>
                      source filing
                    </a>
                  </div>
                </div>
              </div>
              <div className="score" style={{ background: 'var(--surface)', border: `1px solid ${scoreColor(data.citation_score)}` }}>
                <div className="num" style={{ color: scoreColor(data.citation_score) }}>{data.citation_score}</div>
                <div className="lbl" style={{ color: scoreColor(data.citation_score) }}>verified</div>
              </div>
            </div>

            <div className="cols">
              <div className="card bull">
                <div className="h">&#9650; Bull case</div>
                <div className="md"><ReactMarkdown>{data.bull_case}</ReactMarkdown></div>
              </div>
              <div className="card bear">
                <div className="h">&#9660; Bear case</div>
                <div className="md"><ReactMarkdown>{data.bear_case}</ReactMarkdown></div>
              </div>
            </div>

            {(data.bull_rebuttal || data.bear_rebuttal) && (
              <div className="crossfire">
                <div className="cf-h">Crossfire</div>
                {data.bull_rebuttal && (
                  <p className="cf-line"><span className="cf-who bull">Bull responds</span>{data.bull_rebuttal}</p>
                )}
                {data.bear_rebuttal && (
                  <p className="cf-line"><span className="cf-who bear">Bear responds</span>{data.bear_rebuttal}</p>
                )}
              </div>
            )}

            {data.verdict && (
              <div className="verdict">
                <div className="vd-h">The verdict</div>
                <p className="vd-lead">{data.verdict}</p>
                <ul className="vd-list">
                  {data.bull_needs && <li><span className="vd-tag bull">Bull is right if</span>{data.bull_needs}</li>}
                  {data.bear_needs && <li><span className="vd-tag bear">Bear is right if</span>{data.bear_needs}</li>}
                  {data.watch && <li><span className="vd-tag watch">Watch</span>{data.watch}</li>}
                </ul>
              </div>
            )}

            <div className="verify">
              <div className="h">Verification &middot; {data.citation_score} / 100</div>
              <VerifyBody text={data.verifier_report} />
            </div>

            {data.spin && (
              <div className="verify spin">
                <div className="h">Earnings-call spin check &middot; caution {data.spin.caution_score}/100</div>
                <pre>{data.spin.tone_shift}
{'\n'}Red flags:
{data.spin.flags.map((f) => `\n  • ${f}`).join('')}</pre>
              </div>
            )}
            {data.spin_unavailable && (
              <div className="verify spin">
                <div className="h">Earnings-call spin check</div>
                <pre>Not available: {data.spin_unavailable}</pre>
              </div>
            )}

            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, margin: '28px 0 56px' }}>
              <button className="btn" onClick={download}>Download memo</button>
              <button className="btn btn-ghost" onClick={() => nav('/')}>New search</button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
