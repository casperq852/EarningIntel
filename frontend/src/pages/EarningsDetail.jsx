import { useEffect, useRef, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import {
  getSingleEarnings,
  getEarnings,
  getCompany,
  getDocuments,
  getDocumentDownloadUrl,
  getChatSuggestions,
  triggerBackfill,
  triggerFromDocs,
  getBaseURL,
} from '../api/index'

// ---------------------------------------------------------------------------
// Tiny reusable primitives
// ---------------------------------------------------------------------------

function GrowthChip({ value, label }) {
  if (value == null || value === 0) return null
  const pos = value > 0
  return (
    <span className={`inline-flex items-center gap-0.5 text-xs font-semibold px-1.5 py-0.5 rounded ${pos ? 'text-emerald-600 bg-emerald-50' : 'text-red-600 bg-red-50'}`}>
      {pos ? '▲' : '▼'} {Math.abs(value).toFixed(1)}% {label}
    </span>
  )
}

function MetricRow({ label, actual, estimate, surprisePct }) {
  const surpColor = surprisePct == null ? '' : surprisePct > 0 ? 'text-emerald-600' : surprisePct < 0 ? 'text-red-600' : 'text-gray-500'
  return (
    <div className="grid grid-cols-4 gap-4 py-3 border-b border-gray-50 last:border-0">
      <div className="text-sm text-gray-500 font-medium">{label}</div>
      <div className="text-sm font-mono font-semibold text-gray-900 text-right">
        {actual != null ? actual.toLocaleString(undefined, { maximumFractionDigits: 4 }) : '—'}
      </div>
      <div className="text-sm font-mono text-gray-500 text-right">
        {estimate != null ? estimate.toLocaleString(undefined, { maximumFractionDigits: 4 }) : '—'}
      </div>
      <div className={`text-sm font-medium text-right ${surpColor}`}>
        {surprisePct != null ? `${surprisePct > 0 ? '+' : ''}${surprisePct.toFixed(2)}%` : '—'}
      </div>
    </div>
  )
}

function PLRow({ label, value }) {
  if (value == null) return null
  return (
    <div className="flex items-center justify-between py-2 border-b border-gray-50 last:border-0">
      <span className="text-sm text-gray-500">{label}</span>
      <span className="text-sm font-mono font-semibold text-gray-800">
        {value.toLocaleString(undefined, { maximumFractionDigits: 0 })}
      </span>
    </div>
  )
}

function ToneBadge({ value, type }) {
  if (!value) return <span className="text-gray-300">—</span>
  const mgmtColors = { positive: 'bg-emerald-100 text-emerald-800 border-emerald-200', neutral: 'bg-gray-100 text-gray-700 border-gray-200', cautious: 'bg-amber-100 text-amber-800 border-amber-200', negative: 'bg-red-100 text-red-800 border-red-200' }
  const guidanceColors = { raised: 'bg-emerald-100 text-emerald-800 border-emerald-200', maintained: 'bg-blue-100 text-blue-800 border-blue-200', lowered: 'bg-red-100 text-red-800 border-red-200', withdrawn: 'bg-gray-100 text-gray-700 border-gray-200' }
  const colors = type === 'guidance' ? guidanceColors : mgmtColors
  return (
    <span className={`px-3 py-1 rounded-full text-sm font-semibold border capitalize ${colors[value] || 'bg-gray-100 text-gray-500 border-gray-200'}`}>
      {value}
    </span>
  )
}

function BeatMissBadge({ value }) {
  if (!value) return null
  const styles = { beat: 'bg-emerald-500 text-white', miss: 'bg-red-500 text-white', in_line: 'bg-amber-400 text-white' }
  const labels = { beat: '✓ Beat', miss: '✗ Miss', in_line: '≈ In Line' }
  return (
    <span className={`px-4 py-1.5 rounded-full text-sm font-bold ${styles[value] || 'bg-gray-400 text-white'}`}>
      {labels[value] || value}
    </span>
  )
}

const DOC_TYPE_STYLES = {
  press_release:  { bg: 'bg-blue-50',   text: 'text-blue-700',   border: 'border-blue-200',  label: 'Press Release' },
  presentation:   { bg: 'bg-purple-50', text: 'text-purple-700', border: 'border-purple-200', label: 'Presentation' },
  transcript:     { bg: 'bg-teal-50',   text: 'text-teal-700',   border: 'border-teal-200',   label: 'Transcript' },
  announcement:   { bg: 'bg-amber-50',  text: 'text-amber-700',  border: 'border-amber-200',  label: 'Announcement' },
  unknown:        { bg: 'bg-gray-50',   text: 'text-gray-600',   border: 'border-gray-200',   label: 'Document' },
}

function DocTypeTag({ type }) {
  const s = DOC_TYPE_STYLES[type] || DOC_TYPE_STYLES.unknown
  return <span className={`px-2 py-0.5 rounded text-xs font-semibold border ${s.bg} ${s.text} ${s.border}`}>{s.label}</span>
}

function DocumentsSection({ ticker, period }) {
  const [docs, setDocs] = useState([])
  useEffect(() => { getDocuments(ticker, period).then(setDocs).catch(() => {}) }, [ticker, period])
  if (!docs.length) return null
  return (
    <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-6">
      <h2 className="text-base font-semibold text-gray-800 mb-4">Source Documents</h2>
      <ul className="divide-y divide-gray-50">
        {docs.map((doc) => (
          <li key={doc.id} className="flex items-center justify-between py-3 gap-4">
            <div className="flex items-center gap-3 min-w-0">
              <span className="text-lg flex-shrink-0">{doc.mime_type === 'application/pdf' ? '📄' : '🌐'}</span>
              <div className="min-w-0">
                <div className="text-sm font-medium text-gray-800 truncate">{doc.title || doc.source_url}</div>
                <div className="text-xs text-gray-400 truncate mt-0.5">{doc.source_url}</div>
              </div>
            </div>
            <div className="flex items-center gap-2 flex-shrink-0">
              <DocTypeTag type={doc.doc_type} />
              {doc.file_name && (
                <a href={getDocumentDownloadUrl(doc.id)} target="_blank" rel="noreferrer"
                  className="text-xs font-medium text-blue-600 hover:text-blue-800 border border-blue-200 rounded px-2.5 py-1 hover:bg-blue-50 transition-colors">
                  Download
                </a>
              )}
              <a href={doc.source_url} target="_blank" rel="noreferrer"
                className="text-xs font-medium text-gray-500 hover:text-gray-700 border border-gray-200 rounded px-2.5 py-1 hover:bg-gray-50 transition-colors">
                Original
              </a>
            </div>
          </li>
        ))}
      </ul>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Chat panel
// ---------------------------------------------------------------------------

function ChatMessage({ msg }) {
  const isUser = msg.role === 'user'
  return (
    <div className={`flex gap-3 ${isUser ? 'flex-row-reverse' : ''}`}>
      <div className={`w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold flex-shrink-0 mt-0.5 ${isUser ? 'bg-blue-600 text-white' : 'bg-gray-100 text-gray-600'}`}>
        {isUser ? 'PM' : 'AI'}
      </div>
      <div className={`max-w-[85%] rounded-xl px-4 py-2.5 text-sm leading-relaxed whitespace-pre-wrap ${isUser ? 'bg-blue-600 text-white' : 'bg-gray-50 text-gray-800 border border-gray-100'}`}>
        {msg.content}
      </div>
    </div>
  )
}

function ChatPanel({ ticker, period }) {
  const [open, setOpen] = useState(false)
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [suggestions, setSuggestions] = useState([])
  const bottomRef = useRef(null)
  const inputRef = useRef(null)

  useEffect(() => {
    if (open && suggestions.length === 0) {
      getChatSuggestions(ticker, period)
        .then((d) => setSuggestions(d.suggestions || []))
        .catch(() => {})
    }
  }, [open, ticker, period])

  useEffect(() => {
    if (open) bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, open])

  const sendQuestion = async (question) => {
    if (!question.trim() || streaming) return
    const q = question.trim()
    setInput('')
    const newMessages = [...messages, { role: 'user', content: q }]
    setMessages(newMessages)
    setStreaming(true)

    // Placeholder for streaming response
    setMessages([...newMessages, { role: 'assistant', content: '' }])

    try {
      const resp = await fetch(`${getBaseURL()}/chat/${ticker}/${period}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          question: q,
          history: messages.slice(-10),
        }),
      })

      if (!resp.ok) {
        const err = await resp.text()
        setMessages((prev) => {
          const updated = [...prev]
          updated[updated.length - 1] = { role: 'assistant', content: `Error: ${err}` }
          return updated
        })
        return
      }

      const reader = resp.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      let full = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''
        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          const payload = line.slice(6).trim()
          if (payload === '[DONE]') break
          try {
            const chunk = JSON.parse(payload)
            const delta = chunk.choices?.[0]?.delta?.content || ''
            if (delta) {
              full += delta
              setMessages((prev) => {
                const updated = [...prev]
                updated[updated.length - 1] = { role: 'assistant', content: full }
                return updated
              })
            }
          } catch { /* skip malformed chunks */ }
        }
      }
    } catch (e) {
      setMessages((prev) => {
        const updated = [...prev]
        updated[updated.length - 1] = { role: 'assistant', content: `Network error: ${e.message}` }
        return updated
      })
    } finally {
      setStreaming(false)
      setTimeout(() => inputRef.current?.focus(), 50)
    }
  }

  const handleKey = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendQuestion(input) }
  }

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="fixed bottom-6 right-6 flex items-center gap-2 bg-blue-600 hover:bg-blue-700 text-white text-sm font-semibold px-4 py-3 rounded-full shadow-lg transition-all hover:scale-105 z-50"
      >
        <span className="text-base">💬</span> Ask about this report
      </button>
    )
  }

  return (
    <div className="fixed bottom-0 right-0 w-full sm:w-[420px] h-[520px] bg-white border border-gray-200 shadow-2xl rounded-t-2xl sm:rounded-2xl sm:bottom-6 sm:right-6 flex flex-col z-50">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100">
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
          <span className="text-sm font-semibold text-gray-800">Earnings Q&amp;A</span>
          <span className="text-xs text-gray-400">{ticker} · {period}</span>
        </div>
        <div className="flex items-center gap-2">
          {messages.length > 0 && (
            <button onClick={() => setMessages([])} className="text-xs text-gray-400 hover:text-gray-600 px-2 py-1 hover:bg-gray-50 rounded">
              Clear
            </button>
          )}
          <button onClick={() => setOpen(false)} className="text-gray-400 hover:text-gray-600 w-7 h-7 flex items-center justify-center rounded hover:bg-gray-100">
            ✕
          </button>
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.length === 0 ? (
          <div>
            <p className="text-sm text-gray-500 mb-3">Ask any question about this earnings report. Try one of these:</p>
            <div className="space-y-1.5">
              {suggestions.map((s, i) => (
                <button
                  key={i}
                  onClick={() => sendQuestion(s)}
                  className="w-full text-left text-sm px-3 py-2 rounded-lg bg-gray-50 hover:bg-blue-50 hover:text-blue-700 text-gray-700 border border-gray-100 hover:border-blue-200 transition-colors"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        ) : (
          messages.map((msg, i) => <ChatMessage key={i} msg={msg} />)
        )}
        {streaming && messages[messages.length - 1]?.content === '' && (
          <div className="flex gap-3">
            <div className="w-7 h-7 rounded-full bg-gray-100 flex items-center justify-center text-xs font-bold text-gray-600 flex-shrink-0">AI</div>
            <div className="bg-gray-50 border border-gray-100 rounded-xl px-4 py-3 flex gap-1">
              <span className="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
              <span className="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
              <span className="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Suggestions bar (after conversation starts) */}
      {messages.length > 0 && suggestions.length > 0 && !streaming && (
        <div className="px-3 pb-1 flex gap-1.5 overflow-x-auto scrollbar-hide">
          {suggestions.slice(0, 4).map((s, i) => (
            <button key={i} onClick={() => sendQuestion(s)}
              className="text-xs px-2.5 py-1.5 rounded-full bg-gray-100 hover:bg-blue-100 hover:text-blue-700 text-gray-600 whitespace-nowrap flex-shrink-0 transition-colors">
              {s.length > 40 ? s.slice(0, 38) + '…' : s}
            </button>
          ))}
        </div>
      )}

      {/* Input */}
      <div className="p-3 border-t border-gray-100">
        <div className="flex gap-2">
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKey}
            placeholder="Ask a question… (Enter to send)"
            rows={1}
            className="flex-1 resize-none text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            disabled={streaming}
          />
          <button
            onClick={() => sendQuestion(input)}
            disabled={!input.trim() || streaming}
            className="px-3 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            ↑
          </button>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Company context card
// ---------------------------------------------------------------------------

function CompanyContextCard({ company }) {
  if (!company) return null
  const { overview, kpi_rationale, sector, exchange, country, ir_url, custom_kpis } = company
  if (!overview && !kpi_rationale) return null

  return (
    <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-6 space-y-4">
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-center gap-3 flex-wrap">
          {sector && <span className="px-2.5 py-1 bg-blue-50 text-blue-700 text-xs font-semibold rounded-full border border-blue-100">{sector}</span>}
          {exchange && <span className="px-2.5 py-1 bg-gray-50 text-gray-600 text-xs font-semibold rounded-full border border-gray-100">{exchange}</span>}
          {country && <span className="px-2.5 py-1 bg-gray-50 text-gray-600 text-xs font-semibold rounded-full border border-gray-100">{country}</span>}
        </div>
        {ir_url && (
          <a href={ir_url} target="_blank" rel="noreferrer"
            className="text-xs text-blue-600 hover:underline flex items-center gap-1 flex-shrink-0">
            IR Website ↗
          </a>
        )}
      </div>

      {overview && (
        <div>
          <div className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-1">About</div>
          <p className="text-sm text-gray-700 leading-relaxed">{overview}</p>
        </div>
      )}

      {kpi_rationale && (
        <div className="border-t border-gray-50 pt-4">
          <div className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-1">What Analysts Track</div>
          <p className="text-sm text-gray-600 leading-relaxed">{kpi_rationale}</p>
          {custom_kpis?.length > 0 && (
            <div className="flex flex-wrap gap-1.5 mt-2">
              {custom_kpis.map((k) => (
                <span key={k} className="px-2 py-0.5 bg-gray-100 text-gray-600 text-xs rounded font-mono">{k.replace(/_/g, ' ')}</span>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Historical quarters strip
// ---------------------------------------------------------------------------

function QuarterlyHistory({ ticker, currentPeriod }) {
  const [history, setHistory] = useState([])

  useEffect(() => {
    getEarnings(ticker)
      .then((data) => {
        // Keep periods with actual revenue, excluding the stub future quarter
        const withData = (data || [])
          .filter((e) => e.revenue_actual != null)
          .sort((a, b) => {
            // Sort by fiscal_year desc, fiscal_quarter desc
            if (a.fiscal_year !== b.fiscal_year) return (b.fiscal_year || 0) - (a.fiscal_year || 0)
            return (b.fiscal_quarter || 0) - (a.fiscal_quarter || 0)
          })
          .slice(0, 6)
        setHistory(withData)
      })
      .catch(() => {})
  }, [ticker])

  if (history.length < 2) return null

  return (
    <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-6">
      <h2 className="text-base font-semibold text-gray-800 mb-4">Quarterly History</h2>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-100">
              <th className="text-left text-xs font-semibold text-gray-400 uppercase tracking-wide pb-2 pr-4">Period</th>
              <th className="text-right text-xs font-semibold text-gray-400 uppercase tracking-wide pb-2 px-3">Revenue</th>
              <th className="text-right text-xs font-semibold text-gray-400 uppercase tracking-wide pb-2 px-3">EPS</th>
              <th className="text-right text-xs font-semibold text-gray-400 uppercase tracking-wide pb-2 px-3">EBIT Margin</th>
              <th className="text-right text-xs font-semibold text-gray-400 uppercase tracking-wide pb-2 px-3">FCF</th>
              <th className="text-right text-xs font-semibold text-gray-400 uppercase tracking-wide pb-2 pl-3">Beat/Miss</th>
            </tr>
          </thead>
          <tbody>
            {history.map((e) => {
              const pb = e.post_brief || {}
              const margin = pb.ebit_margin_pct ?? null
              const fcf = pb.free_cash_flow ?? null
              const isCurrent = e.fiscal_period === currentPeriod
              return (
                <tr key={e.fiscal_period}
                  className={`border-b border-gray-50 last:border-0 transition-colors ${isCurrent ? 'bg-blue-50/40' : 'hover:bg-gray-50/60'}`}>
                  <td className="py-3 pr-4">
                    <Link to={`/earnings/${ticker}/${e.fiscal_period}`}
                      className={`font-semibold hover:text-blue-600 ${isCurrent ? 'text-blue-700' : 'text-gray-800'}`}>
                      {e.fiscal_period}
                    </Link>
                    {isCurrent && <span className="ml-1.5 text-xs text-blue-500 font-medium">← now</span>}
                  </td>
                  <td className="py-3 px-3 text-right font-mono text-gray-700">
                    {e.revenue_actual != null ? e.revenue_actual.toLocaleString(undefined, { maximumFractionDigits: 0 }) : '—'}
                  </td>
                  <td className="py-3 px-3 text-right font-mono text-gray-700">
                    {e.eps_actual != null ? e.eps_actual.toFixed(2) : '—'}
                  </td>
                  <td className="py-3 px-3 text-right font-mono">
                    {margin != null
                      ? <span className={margin >= 15 ? 'text-emerald-600 font-semibold' : margin >= 8 ? 'text-gray-700' : 'text-amber-600'}>{margin.toFixed(1)}%</span>
                      : <span className="text-gray-300">—</span>}
                  </td>
                  <td className="py-3 px-3 text-right font-mono">
                    {fcf != null
                      ? <span className={fcf >= 0 ? 'text-emerald-600' : 'text-red-600'}>{fcf.toLocaleString(undefined, { maximumFractionDigits: 0 })}</span>
                      : <span className="text-gray-300">—</span>}
                  </td>
                  <td className="py-3 pl-3 text-right">
                    {e.beat_miss
                      ? <span className={`px-2 py-0.5 rounded-full text-xs font-bold ${e.beat_miss === 'beat' ? 'bg-emerald-100 text-emerald-700' : e.beat_miss === 'miss' ? 'bg-red-100 text-red-700' : 'bg-amber-100 text-amber-700'}`}>
                          {e.beat_miss === 'beat' ? '✓ Beat' : e.beat_miss === 'miss' ? '✗ Miss' : '≈ In Line'}
                        </span>
                      : <span className="text-gray-300 text-xs">—</span>}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Auto-synthesis trigger (shown when no brief exists yet)
// ---------------------------------------------------------------------------

function SynthesisGate({ ticker, period, hasDocs, onComplete }) {
  const [status, setStatus] = useState('idle') // idle | running | error
  const [message, setMessage] = useState('')

  const run = async () => {
    setStatus('running')
    setMessage('')
    try {
      if (hasDocs) {
        await triggerFromDocs(ticker, period)
      } else {
        await triggerBackfill(ticker)
      }
      setStatus('done')
      onComplete()
    } catch (e) {
      setStatus('error')
      setMessage(e?.response?.data?.detail || e.message)
    }
  }

  return (
    <div className="bg-white rounded-xl border border-dashed border-gray-200 p-10 text-center">
      <div className="text-4xl mb-4">📊</div>
      <h2 className="text-lg font-semibold text-gray-800 mb-2">No brief generated yet</h2>
      <p className="text-sm text-gray-500 mb-6 max-w-sm mx-auto">
        {hasDocs
          ? 'Documents are already saved — click to run synthesis instantly.'
          : 'Click below to search for IR documents and generate a full earnings brief.'}
      </p>
      {status === 'error' && (
        <div className="text-sm text-red-600 bg-red-50 border border-red-100 rounded-lg px-4 py-2 mb-4 max-w-sm mx-auto">
          {message}
        </div>
      )}
      <button
        onClick={run}
        disabled={status === 'running'}
        className="inline-flex items-center gap-2 bg-blue-600 hover:bg-blue-700 text-white text-sm font-semibold px-6 py-3 rounded-lg disabled:opacity-60 transition-colors"
      >
        {status === 'running' ? (
          <>
            <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24" fill="none">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
            </svg>
            Generating brief…
          </>
        ) : 'Generate Earnings Brief'}
      </button>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function EarningsDetail() {
  const { ticker, period } = useParams()
  const [earnings, setEarnings] = useState(null)
  const [company, setCompany] = useState(null)
  const [docs, setDocs] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const load = () => {
    setLoading(true)
    Promise.all([
      getSingleEarnings(ticker, period).catch(() => null),
      getCompany(ticker).catch(() => null),
      getDocuments(ticker, period).catch(() => []),
    ])
      .then(([e, co, d]) => { setEarnings(e); setCompany(co); setDocs(d || []) })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [ticker, period])

  if (loading) return <div className="flex items-center justify-center h-64 text-gray-400">Loading…</div>
  if (error) return (
    <div className="text-center py-16">
      <div className="text-red-500 mb-2">{error}</div>
      <Link to={`/companies/${ticker}`} className="text-blue-600 hover:underline text-sm">Back to {ticker}</Link>
    </div>
  )

  const hasEarnings = !!earnings
  const hasBrief = hasEarnings && (earnings.post_brief || earnings.pre_brief)
  const hasDocs = docs.length > 0

  const postBrief = earnings?.post_brief
  const preBrief = earnings?.pre_brief
  const customKpis = earnings?.custom_kpis || {}
  const highlights = earnings?.key_highlights || []
  const redFlags = earnings?.red_flags || []

  const segmentBreakdown = postBrief?.segment_breakdown || {}
  const guidanceDetail = postBrief?.guidance_detail
  const yoy = postBrief?.yoy_revenue_growth_pct
  const qoq = postBrief?.qoq_revenue_growth_pct
  const grossProfit = postBrief?.gross_profit
  const ebit = postBrief?.ebit
  const ebitMargin = postBrief?.ebit_margin_pct
  const netIncome = postBrief?.net_income
  const ocf = postBrief?.operating_cash_flow
  const fcf = postBrief?.free_cash_flow
  const capex = postBrief?.capex
  const netDebt = postBrief?.net_debt
  const dps = postBrief?.dividend_per_share
  const orderIntake = postBrief?.order_intake
  const bookToBill = postBrief?.book_to_bill

  const hasSegments = Object.keys(segmentBreakdown).filter((k) => !k.startsWith('__')).length > 0
  const hasPL = grossProfit != null || ebit != null || netIncome != null
  const hasCashFlow = ocf != null || fcf != null || capex != null || netDebt != null || dps != null
  const hasOrderFlow = orderIntake != null || bookToBill != null

  // If no earnings record exists at all, show the synthesis gate
  if (!hasEarnings || !hasBrief) {
    return (
      <div className="space-y-6 max-w-4xl">
        <nav className="text-sm text-gray-500">
          <Link to="/companies" className="hover:text-blue-600">Companies</Link>
          <span className="mx-2">/</span>
          <Link to={`/companies/${ticker}`} className="hover:text-blue-600">{ticker}</Link>
          <span className="mx-2">/</span>
          <span className="text-gray-800 font-medium">{period}</span>
        </nav>
        <div>
          <h1 className="text-2xl font-bold text-gray-900">{company?.name || ticker} — {period}</h1>
        </div>
        <SynthesisGate ticker={ticker} period={period} hasDocs={hasDocs} onComplete={load} />
      </div>
    )
  }

  return (
    <div className="space-y-6 max-w-4xl pb-24">
      {/* Breadcrumb */}
      <nav className="text-sm text-gray-500">
        <Link to="/companies" className="hover:text-blue-600">Companies</Link>
        <span className="mx-2">/</span>
        <Link to={`/companies/${ticker}`} className="hover:text-blue-600">{ticker}</Link>
        <span className="mx-2">/</span>
        <span className="text-gray-800 font-medium">{period}</span>
      </nav>

      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">{company?.name || ticker} — {period}</h1>
          <div className="flex items-center flex-wrap gap-2 mt-2">
            {earnings.report_date && <span className="text-sm text-gray-400">Reported {earnings.report_date}</span>}
            <GrowthChip value={yoy} label="YoY" />
            <GrowthChip value={qoq} label="QoQ" />
          </div>
        </div>
        <BeatMissBadge value={earnings.beat_miss} />
      </div>

      {/* ── Company Context ── */}
      <CompanyContextCard company={company} />

      {/* ── Financials + P&L ── */}
      <div className={`grid gap-6 ${hasPL ? 'grid-cols-1 sm:grid-cols-3' : 'grid-cols-1'}`}>
        <div className={`bg-white rounded-xl border border-gray-100 shadow-sm p-6 ${hasPL ? 'sm:col-span-2' : ''}`}>
          <h2 className="text-base font-semibold text-gray-800 mb-4">Financials</h2>
          <div className="grid grid-cols-4 gap-4 pb-2 mb-1">
            <div className="text-xs font-semibold text-gray-400 uppercase tracking-wide">Metric</div>
            <div className="text-xs font-semibold text-gray-400 uppercase tracking-wide text-right">Actual</div>
            <div className="text-xs font-semibold text-gray-400 uppercase tracking-wide text-right">Estimate</div>
            <div className="text-xs font-semibold text-gray-400 uppercase tracking-wide text-right">Surprise</div>
          </div>
          <MetricRow label="Revenue" actual={earnings.revenue_actual} estimate={earnings.revenue_est} surprisePct={earnings.revenue_surprise_pct} />
          <MetricRow label="EPS" actual={earnings.eps_actual} estimate={earnings.eps_est} surprisePct={earnings.eps_surprise_pct} />
          {(earnings.ebit_est != null || postBrief?.ebit != null) && (
            <MetricRow label="EBIT" actual={postBrief?.ebit ?? null} estimate={earnings.ebit_est} />
          )}
          {(earnings.net_income_est != null || postBrief?.net_income != null) && (
            <MetricRow label="Net Income" actual={postBrief?.net_income ?? null} estimate={earnings.net_income_est} />
          )}
          <div className="flex gap-6 mt-4 pt-4 border-t border-gray-50">
            <div><div className="text-xs text-gray-400 mb-1">Mgmt Tone</div><ToneBadge value={earnings.mgmt_tone} type="mgmt" /></div>
            <div><div className="text-xs text-gray-400 mb-1">Guidance</div><ToneBadge value={earnings.guidance_tone} type="guidance" /></div>
          </div>
        </div>
        {hasPL && (
          <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-6">
            <h2 className="text-base font-semibold text-gray-800 mb-4">P&amp;L Snapshot</h2>
            <PLRow label="Gross Profit" value={grossProfit} />
            <div className="flex items-center justify-between py-2 border-b border-gray-50">
              <span className="text-sm text-gray-500">EBIT</span>
              <div className="text-right">
                {ebit != null && <span className="text-sm font-mono font-semibold text-gray-800">{ebit.toLocaleString(undefined, { maximumFractionDigits: 0 })}</span>}
                {ebitMargin != null && <span className="text-xs text-gray-400 ml-1.5">({ebitMargin.toFixed(1)}%)</span>}
                {ebit == null && <span className="text-sm font-mono text-gray-300">—</span>}
              </div>
            </div>
            <PLRow label="Net Income" value={netIncome} />
          </div>
        )}
      </div>

      {/* ── Segment Breakdown ── */}
      {hasSegments && (
        <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-6">
          <h2 className="text-base font-semibold text-gray-800 mb-4">Segment Breakdown</h2>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-100">
                  <th className="text-left text-xs font-semibold text-gray-400 uppercase tracking-wide pb-2">Segment</th>
                  <th className="text-right text-xs font-semibold text-gray-400 uppercase tracking-wide pb-2">Revenue</th>
                  <th className="text-right text-xs font-semibold text-gray-400 uppercase tracking-wide pb-2">YoY</th>
                  <th className="text-right text-xs font-semibold text-gray-400 uppercase tracking-wide pb-2">Margin %</th>
                  <th className="text-right text-xs font-semibold text-gray-400 uppercase tracking-wide pb-2 pl-4">Bar</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(segmentBreakdown).filter(([k]) => !k.startsWith('__')).map(([name, data]) => {
                  const margin = data?.margin_pct ?? data?.margin ?? null
                  const rev = data?.revenue ?? null
                  const segYoy = data?.yoy_growth_pct ?? null
                  const barColor = margin >= 20 ? 'bg-emerald-400' : margin >= 12 ? 'bg-blue-400' : 'bg-amber-400'
                  return (
                    <tr key={name} className="border-b border-gray-50 last:border-0">
                      <td className="py-3 font-medium text-gray-800">{name}</td>
                      <td className="py-3 text-right font-mono text-gray-700">{rev != null ? rev.toLocaleString() : '—'}</td>
                      <td className="py-3 text-right font-mono text-sm">
                        {segYoy != null ? <span className={segYoy >= 0 ? 'text-emerald-600' : 'text-red-600'}>{segYoy >= 0 ? '+' : ''}{segYoy.toFixed(1)}%</span> : '—'}
                      </td>
                      <td className="py-3 text-right font-mono font-semibold text-gray-900">{margin != null ? `${margin.toFixed(1)}%` : '—'}</td>
                      <td className="py-3 pl-4">
                        {margin != null && (
                          <div className="flex-1 bg-gray-100 rounded-full h-1.5 w-16">
                            <div className={`h-1.5 rounded-full ${barColor}`} style={{ width: `${Math.min(Math.max(margin, 0), 40) * 2.5}%` }} />
                          </div>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ── Cash Flow & Capital ── */}
      {hasCashFlow && (
        <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-6">
          <h2 className="text-base font-semibold text-gray-800 mb-4">Cash Flow &amp; Capital</h2>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
            {ocf != null && (
              <div className="bg-gray-50 rounded-lg p-3">
                <div className="text-xs text-gray-500 mb-1">Operating CF</div>
                <div className="text-lg font-bold text-gray-900 font-mono">{ocf.toLocaleString(undefined, { maximumFractionDigits: 0 })}</div>
              </div>
            )}
            {fcf != null && (
              <div className={`rounded-lg p-3 ${fcf >= 0 ? 'bg-emerald-50' : 'bg-red-50'}`}>
                <div className={`text-xs mb-1 ${fcf >= 0 ? 'text-emerald-600' : 'text-red-600'}`}>Free Cash Flow</div>
                <div className={`text-lg font-bold font-mono ${fcf >= 0 ? 'text-emerald-700' : 'text-red-700'}`}>{fcf.toLocaleString(undefined, { maximumFractionDigits: 0 })}</div>
              </div>
            )}
            {capex != null && (
              <div className="bg-gray-50 rounded-lg p-3">
                <div className="text-xs text-gray-500 mb-1">Capex</div>
                <div className="text-lg font-bold text-gray-900 font-mono">{capex.toLocaleString(undefined, { maximumFractionDigits: 0 })}</div>
              </div>
            )}
            {netDebt != null && (
              <div className={`rounded-lg p-3 ${netDebt > 0 ? 'bg-amber-50' : 'bg-emerald-50'}`}>
                <div className={`text-xs mb-1 ${netDebt > 0 ? 'text-amber-600' : 'text-emerald-600'}`}>Net Debt</div>
                <div className={`text-lg font-bold font-mono ${netDebt > 0 ? 'text-amber-700' : 'text-emerald-700'}`}>{netDebt.toLocaleString(undefined, { maximumFractionDigits: 0 })}</div>
              </div>
            )}
            {dps != null && (
              <div className="bg-blue-50 rounded-lg p-3">
                <div className="text-xs text-blue-600 mb-1">Dividend/Share</div>
                <div className="text-lg font-bold text-blue-900 font-mono">{dps.toFixed(2)}</div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── Order Flow ── */}
      {hasOrderFlow && (
        <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-6">
          <h2 className="text-base font-semibold text-gray-800 mb-4">Order Flow</h2>
          <div className="grid grid-cols-2 gap-4">
            {orderIntake != null && (
              <div className="bg-gray-50 rounded-lg p-3">
                <div className="text-xs text-gray-500 mb-1">Order Intake</div>
                <div className="text-lg font-bold text-gray-900 font-mono">{orderIntake.toLocaleString(undefined, { maximumFractionDigits: 0 })}</div>
              </div>
            )}
            {bookToBill != null && (
              <div className={`rounded-lg p-3 ${bookToBill >= 1 ? 'bg-emerald-50' : 'bg-amber-50'}`}>
                <div className={`text-xs mb-1 ${bookToBill >= 1 ? 'text-emerald-600' : 'text-amber-600'}`}>Book-to-Bill</div>
                <div className={`text-2xl font-bold font-mono ${bookToBill >= 1 ? 'text-emerald-700' : 'text-amber-700'}`}>{bookToBill.toFixed(2)}x</div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── Guidance Detail ── */}
      {guidanceDetail && (
        <div className="bg-blue-50 border border-blue-100 rounded-xl p-6">
          <div className="flex items-center gap-2 mb-2">
            <span className="text-blue-500 text-lg">→</span>
            <h2 className="text-base font-semibold text-blue-900">Guidance</h2>
            <ToneBadge value={earnings.guidance_tone} type="guidance" />
          </div>
          <p className="text-sm text-blue-800 leading-relaxed">{guidanceDetail}</p>
        </div>
      )}

      {/* ── Key Highlights ── */}
      {highlights.length > 0 && (
        <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-6">
          <h2 className="text-base font-semibold text-gray-800 mb-4">Key Highlights</h2>
          <ul className="space-y-3">
            {highlights.map((h, i) => (
              <li key={i} className="flex items-start gap-3">
                <span className="w-5 h-5 rounded-full bg-blue-100 text-blue-700 text-xs font-bold flex items-center justify-center flex-shrink-0 mt-0.5">{i + 1}</span>
                <span className="text-sm text-gray-700 leading-relaxed">{h}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* ── Red Flags ── */}
      {redFlags.length > 0 && (
        <div className="bg-red-50 rounded-xl border border-red-100 p-6">
          <h2 className="text-base font-semibold text-red-800 mb-4 flex items-center gap-2"><span>⚠</span> Red Flags</h2>
          <ul className="space-y-2">
            {redFlags.map((flag, i) => (
              <li key={i} className="flex items-start gap-3">
                <span className="w-5 h-5 rounded-full bg-red-200 text-red-700 text-xs font-bold flex items-center justify-center flex-shrink-0 mt-0.5">!</span>
                <span className="text-sm text-red-800 leading-relaxed">{flag}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* ── Custom KPIs ── */}
      {Object.keys(customKpis).length > 0 && (
        <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-6">
          <h2 className="text-base font-semibold text-gray-800 mb-4">Custom KPIs</h2>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            {Object.entries(customKpis).map(([key, val]) => (
              <div key={key} className="bg-gray-50 rounded-lg p-3">
                <div className="text-xs text-gray-500 mb-1 capitalize">{key.replace(/_/g, ' ')}</div>
                <div className="text-xl font-bold text-gray-900 font-mono">
                  {val != null ? (typeof val === 'number' ? val.toFixed(2) : val) : <span className="text-gray-300 text-sm">n/a</span>}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Post-Earnings Brief ── */}
      {postBrief?.post_brief && (
        <div className="bg-white rounded-xl border border-emerald-100 shadow-sm p-6">
          <div className="flex items-center gap-2 mb-4">
            <span className="w-2 h-2 rounded-full bg-emerald-500" />
            <h2 className="text-base font-semibold text-gray-800">Post-Earnings Brief</h2>
          </div>
          <p className="text-gray-700 leading-relaxed text-sm">{postBrief.post_brief}</p>
        </div>
      )}

      {/* ── Pre-Earnings Brief ── */}
      {preBrief && !postBrief && (
        <div className="bg-white rounded-xl border border-blue-100 shadow-sm p-6">
          <div className="flex items-center gap-2 mb-4">
            <span className="w-2 h-2 rounded-full bg-blue-400" />
            <h2 className="text-base font-semibold text-gray-800">Pre-Earnings Brief</h2>
          </div>
          {preBrief.consensus_summary && <p className="text-gray-700 leading-relaxed text-sm mb-4">{preBrief.consensus_summary}</p>}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {preBrief.bull_case && <div className="bg-emerald-50 rounded-lg p-4"><div className="text-xs font-semibold text-emerald-700 mb-1">Bull Case</div><p className="text-sm text-gray-700">{preBrief.bull_case}</p></div>}
            {preBrief.bear_case && <div className="bg-red-50 rounded-lg p-4"><div className="text-xs font-semibold text-red-700 mb-1">Bear Case</div><p className="text-sm text-gray-700">{preBrief.bear_case}</p></div>}
          </div>
          {preBrief.key_watch_items?.length > 0 && (
            <div className="mt-4">
              <div className="text-xs font-semibold text-gray-500 mb-2 uppercase tracking-wide">Key Watch Items</div>
              <ul className="space-y-1">
                {preBrief.key_watch_items.map((item, i) => (
                  <li key={i} className="text-sm text-gray-700 flex items-start gap-2"><span className="text-blue-400">→</span>{item}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {/* ── Source Documents ── */}
      {docs.length > 0 && (
        <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-6">
          <h2 className="text-base font-semibold text-gray-800 mb-4">Source Documents</h2>
          <ul className="divide-y divide-gray-50">
            {docs.map((doc) => (
              <li key={doc.id} className="flex items-center justify-between py-3 gap-4">
                <div className="flex items-center gap-3 min-w-0">
                  <span className="text-lg flex-shrink-0">{doc.mime_type === 'application/pdf' ? '📄' : '🌐'}</span>
                  <div className="min-w-0">
                    <div className="text-sm font-medium text-gray-800 truncate">{doc.title || doc.source_url}</div>
                    <div className="text-xs text-gray-400 truncate mt-0.5">{doc.source_url}</div>
                  </div>
                </div>
                <div className="flex items-center gap-2 flex-shrink-0">
                  <DocTypeTag type={doc.doc_type} />
                  {doc.file_name && (
                    <a href={getDocumentDownloadUrl(doc.id)} target="_blank" rel="noreferrer"
                      className="text-xs font-medium text-blue-600 hover:text-blue-800 border border-blue-200 rounded px-2.5 py-1 hover:bg-blue-50 transition-colors">
                      Download
                    </a>
                  )}
                  <a href={doc.source_url} target="_blank" rel="noreferrer"
                    className="text-xs font-medium text-gray-500 hover:text-gray-700 border border-gray-200 rounded px-2.5 py-1 hover:bg-gray-50 transition-colors">
                    Original
                  </a>
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* ── Quarterly History ── */}
      <QuarterlyHistory ticker={ticker} currentPeriod={period} />

      {/* Floating chat */}
      <ChatPanel ticker={ticker} period={period} />
    </div>
  )
}
