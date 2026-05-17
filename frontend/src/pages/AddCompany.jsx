import { useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { createCompany, getBaseURL } from '../api/index'

const SECTORS = [
  'Technology', 'Semiconductors', 'Industrials', 'Healthcare', 'Pharmaceuticals',
  'Financials', 'Banks', 'Consumer Discretionary', 'Consumer Staples',
  'Energy', 'Materials', 'Real Estate', 'Utilities', 'Communication Services',
]

const EXCHANGES = [
  'NASDAQ', 'NYSE', 'XETRA', 'Euronext', 'LSE', 'SIX', 'OMX', 'Euronext Amsterdam',
  'Euronext Paris', 'BME', 'Borsa Italiana',
]

function OnboardLog({ ticker, onDone }) {
  const [events, setEvents] = useState([])
  const [phase, setPhase] = useState('connecting') // connecting | running | done | error
  const [started, setStarted] = useState(false)

  const startOnboard = async () => {
    if (started) return
    setStarted(true)
    setPhase('running')

    const url = `${getBaseURL()}/onboard/${ticker}`
    try {
      const resp = await fetch(url, { method: 'POST' })
      const reader = resp.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''
        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          try {
            const evt = JSON.parse(line.slice(6))
            setEvents((prev) => [...prev, evt])
            if (evt.type === 'done') {
              setPhase('done')
              setTimeout(() => onDone(), 1200)
            } else if (evt.type === 'error') {
              setPhase('error')
            }
          } catch { /* skip malformed */ }
        }
      }
    } catch (e) {
      setEvents((prev) => [...prev, { type: 'error', message: e.message }])
      setPhase('error')
    }
  }

  // Auto-start on mount
  if (!started) startOnboard()

  const iconFor = (type) => {
    if (type === 'tool_call') return '🔍'
    if (type === 'tool_result') return '📄'
    if (type === 'progress') return '⚙️'
    if (type === 'done') return '✅'
    if (type === 'error') return '❌'
    return '•'
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        {phase === 'running' && (
          <svg className="animate-spin h-5 w-5 text-blue-500" viewBox="0 0 24 24" fill="none">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
          </svg>
        )}
        {phase === 'done' && <span className="text-2xl">✅</span>}
        {phase === 'error' && <span className="text-2xl">❌</span>}
        <div>
          <div className="font-semibold text-gray-800">
            {phase === 'connecting' && 'Starting research agent…'}
            {phase === 'running' && `Researching ${ticker}…`}
            {phase === 'done' && 'Onboarding complete — redirecting…'}
            {phase === 'error' && 'Research encountered an error'}
          </div>
          <div className="text-xs text-gray-400">Claude is searching IR websites and earnings documents</div>
        </div>
      </div>

      <div className="bg-gray-900 rounded-xl p-4 h-72 overflow-y-auto font-mono text-xs space-y-1.5">
        {events.map((evt, i) => (
          <div key={i} className={`flex gap-2 ${evt.type === 'error' ? 'text-red-400' : evt.type === 'done' ? 'text-emerald-400' : 'text-gray-300'}`}>
            <span className="flex-shrink-0">{iconFor(evt.type)}</span>
            <span className="break-all">
              {evt.type === 'tool_call' && `[${evt.tool}] ${evt.input}`}
              {evt.type === 'tool_result' && `→ ${evt.preview}`}
              {evt.type === 'progress' && evt.message}
              {evt.type === 'done' && `Done — saved: ${JSON.stringify(evt.saved || {})}`}
              {evt.type === 'error' && evt.message}
            </span>
          </div>
        ))}
        {phase === 'running' && events.length === 0 && (
          <div className="text-gray-500">Connecting…</div>
        )}
      </div>
    </div>
  )
}

export default function AddCompany() {
  const navigate = useNavigate()
  const [step, setStep] = useState('form') // form | onboarding
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [ticker, setTicker] = useState('')
  const [form, setForm] = useState({
    name: '',
    sector: '',
    exchange: '',
    country: '',
    fmp_symbol: '',
  })

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError('')
    if (!ticker.trim() || !form.name.trim()) {
      setError('Ticker and company name are required.')
      return
    }
    setSaving(true)
    try {
      await createCompany({ ticker: ticker.trim().toUpperCase(), ...form })
      setStep('onboarding')
    } catch (err) {
      const detail = err?.response?.data?.detail || err.message
      setError(typeof detail === 'string' ? detail : JSON.stringify(detail))
    } finally {
      setSaving(false)
    }
  }

  if (step === 'onboarding') {
    return (
      <div className="max-w-2xl space-y-6">
        <nav className="text-sm text-gray-500">
          <Link to="/companies" className="hover:text-blue-600">Companies</Link>
          <span className="mx-2">/</span>
          <span className="text-gray-800 font-medium">Add Company</span>
        </nav>
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Onboarding {ticker.toUpperCase()}</h1>
          <p className="text-gray-500 mt-1 text-sm">The research agent is gathering IR data, earnings history, and sector KPIs.</p>
        </div>
        <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-6">
          <OnboardLog ticker={ticker.toUpperCase()} onDone={() => navigate(`/companies/${ticker.toUpperCase()}`)} />
        </div>
      </div>
    )
  }

  return (
    <div className="max-w-xl space-y-6">
      <nav className="text-sm text-gray-500">
        <Link to="/companies" className="hover:text-blue-600">Companies</Link>
        <span className="mx-2">/</span>
        <span className="text-gray-800 font-medium">Add Company</span>
      </nav>

      <div>
        <h1 className="text-2xl font-bold text-gray-900">Add Company</h1>
        <p className="text-gray-500 mt-1 text-sm">
          After saving, the research agent will automatically find the IR website, earnings history, and sector KPIs.
        </p>
      </div>

      <form onSubmit={handleSubmit} className="bg-white rounded-xl border border-gray-100 shadow-sm p-6 space-y-5">
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Ticker <span className="text-red-500">*</span></label>
            <input
              type="text"
              value={ticker}
              onChange={(e) => setTicker(e.target.value.toUpperCase())}
              placeholder="e.g. ASML"
              required
              className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 font-mono uppercase"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Company Name <span className="text-red-500">*</span></label>
            <input
              type="text"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              placeholder="e.g. ASML Holding"
              required
              className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Sector</label>
            <select
              value={form.sector}
              onChange={(e) => setForm({ ...form, sector: e.target.value })}
              className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white"
            >
              <option value="">Select sector…</option>
              {SECTORS.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Exchange</label>
            <select
              value={form.exchange}
              onChange={(e) => setForm({ ...form, exchange: e.target.value })}
              className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white"
            >
              <option value="">Select exchange…</option>
              {EXCHANGES.map((x) => <option key={x} value={x}>{x}</option>)}
            </select>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Country</label>
            <input
              type="text"
              value={form.country}
              onChange={(e) => setForm({ ...form, country: e.target.value.toUpperCase().slice(0, 2) })}
              placeholder="e.g. NL, DE, US"
              maxLength={2}
              className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 font-mono uppercase"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              FMP Symbol
              <span className="text-gray-400 font-normal ml-1 text-xs">(optional)</span>
            </label>
            <input
              type="text"
              value={form.fmp_symbol}
              onChange={(e) => setForm({ ...form, fmp_symbol: e.target.value })}
              placeholder="e.g. ASML.AS"
              className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 font-mono"
            />
          </div>
        </div>

        {error && (
          <div className="text-sm text-red-600 bg-red-50 border border-red-100 rounded-lg px-4 py-2.5">
            {error}
          </div>
        )}

        <div className="flex items-center justify-between pt-2">
          <Link to="/companies" className="text-sm text-gray-500 hover:text-gray-700">
            Cancel
          </Link>
          <button
            type="submit"
            disabled={saving}
            className="inline-flex items-center gap-2 bg-blue-600 hover:bg-blue-700 text-white text-sm font-semibold px-6 py-2.5 rounded-lg disabled:opacity-60 transition-colors"
          >
            {saving ? (
              <>
                <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24" fill="none">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
                </svg>
                Saving…
              </>
            ) : 'Save & Start Research'}
          </button>
        </div>
      </form>

      <div className="bg-blue-50 border border-blue-100 rounded-xl p-4 text-sm text-blue-700">
        <strong>What happens next:</strong> Claude will search the company's investor relations website, extract the last 2–3 quarters of financials (including segment breakdowns), identify sector-specific KPIs, and generate a qualitative assessment — all automatically.
      </div>
    </div>
  )
}
