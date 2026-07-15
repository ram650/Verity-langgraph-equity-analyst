// In production set VITE_API_BASE to your deployed backend URL (build-time env).
// Falls back to the local dev backend.
export const BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8001'

export async function getSuggested() {
  const r = await fetch(`${BASE}/suggested`)
  return r.json()
}

export async function getQuotes() {
  const r = await fetch(`${BASE}/quotes`)
  return r.json()
}

export async function resolveQuery(q) {
  const r = await fetch(`${BASE}/resolve?q=${encodeURIComponent(q)}`)
  if (!r.ok) throw new Error('no match')
  return r.json()   // { ticker, name }
}

export async function analyze(ticker, quarter) {
  const r = await fetch(`${BASE}/analyze`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ticker, quarter: quarter || null }),
  })
  if (!r.ok) {
    const e = await r.json().catch(() => ({ detail: 'Request failed' }))
    throw new Error(e.detail || 'Request failed')
  }
  return r.json()
}
