import { useEffect, useRef, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
} from 'recharts'
import { getCompany, getEarnings, triggerPreBrief, triggerPostBrief, getBaseURL, getBaseURL as baseURL } from '../api/index'
import client from '../api/client'

function BeatMissBadge({ value }) {
  if (!value) return <span className="text-gray-300">—</span>
  const styles = {
    beat: 'bg-emerald-100 text-emerald-700',
    miss: 'bg-red-100 text-red-700',
    in_line: 'bg-amber-100 text-amber-700',
  }
  const labels = { beat: 'Beat', miss: 'Miss', in_line: 'In Line' }
  return (
    <span className={`px-2 py-0.5 rounded text-xs font-medium ${styles[value] || 'bg-gray-100 text-gray-500'}`}>
      {labels[value] || value}
    </span>
  )
}

function ToneBadge({ value, type }) {
  if (!value) return <span className="text-gray-300">—</span>
  const mgmtColors = {
    positive: 'bg-emerald-100 text-emerald-700',
    neutral: 'bg-gray-100 text-gray-600',
    cautious: 'bg-amber-100 text-amber-700',
    negative: 'bg-red-100 text-red-700',
  }
  const guidanceColors = {
    raised: 'bg-emerald-100 text-emerald-700',
    maintained: 'bg-blue-100 text-blue-700',
    lowered: 'bg-red-100 text-red-700',
    withdrawn: 'bg-gray-100 text-gray-600',
  }
  const colors = type === 'guidance' ? guidanceColors : mgmtColors
  return (
    <span className={`px-2 py-0.5 rounded text-xs font-medium capitalize ${colors[value] || 'bg-gray-100 text-gray-500'}`}>
      {value}
    </span>
  )
}

const CHART_COLORS = ['#3b82f6', '#10b981', '#f59e0b', '#8b5cf6', '#ef4444']

// ---------------------------------------------------------------------------
// Research (onboarding) panel — streams live Claude agent progress
// ---------------------------------------------------------------------------

function ToolCallLine({ event }) {
  if (event.type === 'tool_call') {
    const icon = event.tool === 'search_web' ? '🔍' : '📄'
    return (
      <div className="flex items-start gap-2 py-1">
        <span className="text-base flex-shrink-0">{icon}</span>
        <span className="text-xs text-gray-600 font-mono break-all">{event.input}</span>
      </div>
    )
  }
  if (event.type === 'tool_result') {
    return (
      <div className="ml-6 text-xs text-gray-400 italic truncate pb-1">{event.preview}</div>
    )
  }
  if (event.type === 'progress') {
    return <div className="text-xs text-blue-600 py-0.5 font-medium">{event.message}</div>
  }
  return null
}

// ---------------------------------------------------------------------------
// Bloomberg model upload
// ---------------------------------------------------------------------------

function BloombergModelUpload({ ticker, onDone }) {
  const [status, setStatus] = useState('idle') // idle | uploading | done | error
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')
  const fileRef = useRef(null)

  const handleFile = async (e) => {
    const file = e.target.files?.[0]
    if (!file) return
    setStatus('uploading')
    setResult(null)
    setError('')

    const form = new FormData()
    form.append('file', file)

    try {
      const res = await client.post(`/companies/${ticker}/upload-model`, form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      setResult(res.data)
      setStatus('done')
      onDone()
    } catch (e) {
      setError(e?.response?.data?.detail || e.message)
      setStatus('error')
    } finally {
      // Reset file input so the same file can be re-uploaded
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  return (
    <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-base font-semibold text-gray-800">Bloomberg Analyst Model</h2>
          <p className="text-xs text-gray-400 mt-0.5">
            Upload the aggregate analyst model .xlsx from Bloomberg — Claude will extract consensus estimates per quarter.
          </p>
        </div>

        <label className={`shrink-0 cursor-pointer flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
          status === 'uploading'
            ? 'bg-gray-100 text-gray-400 pointer-events-none'
            : 'bg-indigo-600 hover:bg-indigo-700 text-white'
        }`}>
          {status === 'uploading' ? (
            <>
              <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24" fill="none">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
              </svg>
              Parsing…
            </>
          ) : (
            <>↑ Upload .xlsx</>
          )}
          <input
            ref={fileRef}
            type="file"
            accept=".xlsx,.xls"
            className="hidden"
            onChange={handleFile}
            disabled={status === 'uploading'}
          />
        </label>
      </div>

      {status === 'error' && (
        <div className="mt-3 text-sm text-red-600 bg-red-50 border border-red-100 rounded-lg px-3 py-2">
          {error}
        </div>
      )}

      {status === 'done' && result && (
        <div className="mt-4 space-y-3">
          <div className="flex items-center gap-2 text-sm text-emerald-700 font-medium">
            <span>✓</span>
            <span>
              Parsed {result.parsed_periods} period{result.parsed_periods !== 1 ? 's' : ''} · saved {result.saved?.length ?? 0}
              {result.currency ? ` · ${result.currency}` : ''}
            </span>
          </div>

          {result.saved?.length > 0 && (
            <div className="overflow-x-auto">
              <table className="w-full text-xs border-collapse">
                <thead>
                  <tr className="bg-gray-50 border-b border-gray-100">
                    <th className="text-left px-3 py-2 font-semibold text-gray-500">Period</th>
                    <th className="text-right px-3 py-2 font-semibold text-gray-500">Type</th>
                    <th className="text-right px-3 py-2 font-semibold text-gray-500">Revenue</th>
                    <th className="text-right px-3 py-2 font-semibold text-gray-500">EBIT</th>
                    <th className="text-right px-3 py-2 font-semibold text-gray-500">EPS</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-50">
                  {result.saved.map((q) => (
                    <tr key={q.fiscal_period} className="hover:bg-gray-50">
                      <td className="px-3 py-2 font-mono font-medium text-gray-800">{q.fiscal_period}</td>
                      <td className="px-3 py-2 text-right">
                        <span className={`px-1.5 py-0.5 rounded text-xs ${q.is_estimate ? 'bg-blue-50 text-blue-600' : 'bg-gray-100 text-gray-500'}`}>
                          {q.is_estimate ? 'Est' : 'Actual'}
                        </span>
                      </td>
                      <td className="px-3 py-2 text-right text-gray-700 tabular-nums">
                        {q.revenue != null ? `${result.currency || ''}${q.revenue >= 1000 ? `${(q.revenue/1000).toFixed(1)}bn` : `${Math.round(q.revenue)}m`}` : '—'}
                      </td>
                      <td className="px-3 py-2 text-right text-gray-700 tabular-nums">
                        {q.ebit != null ? `${result.currency || ''}${q.ebit >= 1000 ? `${(q.ebit/1000).toFixed(1)}bn` : `${Math.round(q.ebit)}m`}` : '—'}
                      </td>
                      <td className="px-3 py-2 text-right text-gray-700 tabular-nums">
                        {q.eps != null ? q.eps.toFixed(2) : '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <button
            onClick={() => setStatus('idle')}
            className="text-xs text-gray-400 hover:text-gray-600"
          >
            Upload another file
          </button>
        </div>
      )}
    </div>
  )
}

function AlphieResearch({ ticker }) {
  const [state, setState] = useState('idle') // idle | loading | done | error
  const [data, setData] = useState(null)
  const [error, setError] = useState('')

  const load = async () => {
    setState('loading')
    try {
      const res = await client.get(`/companies/${ticker}/research`)
      setData(res.data)
      setState('done')
    } catch (e) {
      setError(e?.response?.data?.detail || e.message)
      setState('error')
    }
  }

  if (state === 'idle') {
    return (
      <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-6">
        <div className="flex items-center justify-between mb-2">
          <div>
            <h2 className="text-base font-semibold text-gray-800">Analyst Research</h2>
            <p className="text-xs text-gray-400 mt-0.5">Powered by Alphie RAG — 2,300+ analyst reports</p>
          </div>
          <button
            onClick={load}
            className="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white text-sm font-medium rounded-lg transition-colors"
          >
            Pull Research
          </button>
        </div>
      </div>
    )
  }

  if (state === 'loading') {
    return (
      <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-6 flex items-center gap-3">
        <svg className="animate-spin h-5 w-5 text-indigo-500" viewBox="0 0 24 24" fill="none">
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
        </svg>
        <span className="text-sm text-gray-600">Querying analyst research database…</span>
      </div>
    )
  }

  if (state === 'error') {
    return (
      <div className="bg-red-50 rounded-xl border border-red-100 p-6">
        <div className="text-sm text-red-600 font-medium mb-1">Research query failed</div>
        <div className="text-xs text-red-500">{error}</div>
      </div>
    )
  }

  const sources = data?.sources || []

  return (
    <div className="bg-white rounded-xl border border-indigo-100 shadow-sm p-6">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="text-base font-semibold text-gray-800 flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-indigo-500" />
            Analyst Research
          </h2>
          <p className="text-xs text-gray-400 mt-0.5">Alphie RAG · {sources.length} source{sources.length !== 1 ? 's' : ''}</p>
        </div>
        <button onClick={load} className="text-xs text-indigo-600 hover:underline">Refresh</button>
      </div>

      <div className="prose prose-sm max-w-none text-gray-700 leading-relaxed whitespace-pre-wrap text-sm">
        {data?.answer || 'No research found for this company.'}
      </div>

      {sources.length > 0 && (
        <div className="mt-4 pt-4 border-t border-gray-50">
          <div className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">Sources</div>
          <ul className="space-y-1">
            {sources.slice(0, 5).map((s, i) => (
              <li key={i} className="text-xs text-gray-500 truncate">
                📄 {s.filename || s.source || 'Unknown'}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

function ResearchPanel({ ticker, onDone }) {
  const [status, setStatus] = useState('idle') // idle | running | done | error
  const [events, setEvents] = useState([])
  const [result, setResult] = useState(null)
  const [errorMsg, setErrorMsg] = useState('')
  const logRef = useRef(null)

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight
  }, [events])

  const run = async () => {
    setStatus('running')
    setEvents([])
    setResult(null)
    setErrorMsg('')

    try {
      const resp = await fetch(`${getBaseURL()}/onboard/${ticker}`, { method: 'POST' })
      if (!resp.ok) {
        const body = await resp.text()
        throw new Error(body)
      }

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
            const event = JSON.parse(line.slice(6))
            setEvents((prev) => [...prev, event])
            if (event.type === 'done') {
              setResult(event.data)
              setStatus('done')
              onDone()
            } else if (event.type === 'error') {
              setErrorMsg(event.message)
              setStatus('error')
            }
          } catch { /* skip */ }
        }
      }
      if (status === 'running') setStatus('done')
    } catch (e) {
      setErrorMsg(e.message)
      setStatus('error')
    }
  }

  return (
    <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-6">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="text-base font-semibold text-gray-800">Research Company</h2>
          <p className="text-xs text-gray-500 mt-0.5">
            Claude will find the IR website, extract recent results, and identify key KPIs.
          </p>
        </div>
        {status === 'idle' || status === 'error' ? (
          <button
            onClick={run}
            className="flex items-center gap-2 bg-blue-600 hover:bg-blue-700 text-white text-sm font-semibold px-4 py-2 rounded-lg transition-colors"
          >
            <span>🔬</span> Run Research
          </button>
        ) : status === 'running' ? (
          <div className="flex items-center gap-2 text-sm text-blue-600 font-medium">
            <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24" fill="none">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
            </svg>
            Researching…
          </div>
        ) : (
          <div className="flex items-center gap-2">
            <span className="text-emerald-600 text-sm font-medium">✓ Done</span>
            <button onClick={run} className="text-xs text-gray-400 hover:text-gray-600 border border-gray-200 rounded px-2 py-1">
              Re-run
            </button>
          </div>
        )}
      </div>

      {/* Live log */}
      {events.length > 0 && (
        <div
          ref={logRef}
          className="bg-gray-50 rounded-lg p-3 max-h-56 overflow-y-auto space-y-0.5 text-sm border border-gray-100"
        >
          {events.filter((e) => ['tool_call', 'tool_result', 'progress'].includes(e.type)).map((e, i) => (
            <ToolCallLine key={i} event={e} />
          ))}
          {status === 'running' && (
            <div className="flex gap-1 pt-1 pl-1">
              <span className="w-1.5 h-1.5 bg-blue-400 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
              <span className="w-1.5 h-1.5 bg-blue-400 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
              <span className="w-1.5 h-1.5 bg-blue-400 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
            </div>
          )}
        </div>
      )}

      {/* Error */}
      {status === 'error' && (
        <div className="mt-3 text-sm text-red-600 bg-red-50 border border-red-100 rounded-lg px-3 py-2">
          {errorMsg}
        </div>
      )}

      {/* Summary card */}
      {result && (
        <div className="mt-4 space-y-3">
          {result.company_overview && (
            <p className="text-sm text-gray-700 leading-relaxed">{result.company_overview}</p>
          )}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {result.ir_url && (
              <div className="bg-blue-50 rounded-lg p-3">
                <div className="text-xs font-semibold text-blue-600 mb-1">IR Website</div>
                <a href={result.ir_url} target="_blank" rel="noreferrer"
                  className="text-sm text-blue-700 hover:text-blue-900 truncate block">
                  {result.ir_url}
                </a>
              </div>
            )}
            {result.next_earnings_date && (
              <div className="bg-amber-50 rounded-lg p-3">
                <div className="text-xs font-semibold text-amber-600 mb-1">Next Earnings</div>
                <div className="text-sm font-semibold text-amber-800">{result.next_earnings_date}</div>
              </div>
            )}
          </div>
          {result.custom_kpis?.length > 0 && (
            <div className="bg-gray-50 rounded-lg p-3">
              <div className="text-xs font-semibold text-gray-500 mb-2">KPIs to Track</div>
              <div className="flex flex-wrap gap-1.5">
                {result.custom_kpis.map((kpi) => (
                  <span key={kpi} className="px-2 py-0.5 bg-white border border-gray-200 rounded text-xs font-mono text-gray-700">
                    {kpi}
                  </span>
                ))}
              </div>
              {result.kpi_rationale && (
                <p className="text-xs text-gray-500 mt-2 italic">{result.kpi_rationale}</p>
              )}
            </div>
          )}
          {result.latest_earnings_summary && (
            <div className="bg-emerald-50 rounded-lg p-3">
              <div className="text-xs font-semibold text-emerald-600 mb-1">Latest Earnings Assessment</div>
              <p className="text-sm text-gray-700 leading-relaxed">{result.latest_earnings_summary}</p>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default function CompanyDetail() {
  const { ticker } = useParams()
  const [company, setCompany] = useState(null)
  const [earnings, setEarnings] = useState([])
  const [loading, setLoading] = useState(true)
  const [synthLoading, setSynthLoading] = useState(null)
  const [synthMsg, setSynthMsg] = useState(null)

  useEffect(() => {
    setLoading(true)
    Promise.all([getCompany(ticker), getEarnings(ticker)])
      .then(([co, earn]) => {
        setCompany(co)
        setEarnings(earn)
      })
      .finally(() => setLoading(false))
  }, [ticker])

  const handleSynth = async (type) => {
    setSynthLoading(type)
    setSynthMsg(null)
    try {
      const fn = type === 'pre' ? triggerPreBrief : triggerPostBrief
      await fn(ticker)
      setSynthMsg({ type: 'success', text: `${type === 'pre' ? 'Pre' : 'Post'}-brief generated successfully.` })
      // Refresh earnings
      const earn = await getEarnings(ticker)
      setEarnings(earn)
    } catch (e) {
      setSynthMsg({ type: 'error', text: e.message })
    } finally {
      setSynthLoading(null)
    }
  }

  if (loading) {
    return <div className="flex items-center justify-center h-64 text-gray-400">Loading…</div>
  }
  if (!company) {
    return <div className="text-red-500">Company not found.</div>
  }

  // Build KPI chart data from earnings history
  const customKpis = company.custom_kpis || []
  const chartKpis = customKpis.slice(0, 2)
  const chartData = [...earnings]
    .reverse()
    .slice(-8)
    .map((e) => {
      const kpis = e.custom_kpis || {}
      const point = { period: e.fiscal_period }
      chartKpis.forEach((kpi) => {
        point[kpi] = kpis[kpi] ?? null
      })
      return point
    })
    .filter((p) => chartKpis.some((k) => p[k] !== null))

  const latestEarnings = earnings[0]
  const latestBrief = latestEarnings?.post_brief || latestEarnings?.pre_brief

  // Bloomberg banner logic
  const hasAnyActuals = earnings.some((e) => e.revenue_actual != null)
  const today = new Date()
  const pastEarnings = earnings.filter((e) => {
    if (!e.report_date) return false
    return new Date(e.report_date) <= today
  })
  const latestPastMissingActuals = pastEarnings.length > 0 && pastEarnings[0].revenue_actual == null
  const showBloombergBanner = !hasAnyActuals || latestPastMissingActuals

  const refreshAll = () => {
    Promise.all([getCompany(ticker), getEarnings(ticker)]).then(([co, earn]) => {
      setCompany(co)
      setEarnings(earn)
    })
  }

  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4">
        <div>
          <div className="flex items-center gap-3">
            <span className="text-3xl font-bold text-gray-900 font-mono">{company.ticker}</span>
            {company.exchange && (
              <span className="text-sm font-mono bg-gray-100 text-gray-600 px-2 py-0.5 rounded">
                {company.exchange}
              </span>
            )}
          </div>
          <h1 className="text-xl font-semibold text-gray-700 mt-1">{company.name}</h1>
          <div className="flex flex-wrap gap-2 mt-2">
            {company.sector && (
              <span className="px-2 py-0.5 bg-purple-50 text-purple-700 rounded text-xs font-medium">
                {company.sector}
              </span>
            )}
            {company.country && (
              <span className="px-2 py-0.5 bg-blue-50 text-blue-700 rounded text-xs font-medium">
                {company.country}
              </span>
            )}
          </div>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => handleSynth('pre')}
            disabled={synthLoading === 'pre'}
            className="px-3 py-2 text-sm font-medium bg-white border border-gray-200 text-gray-700 rounded-lg hover:bg-gray-50 disabled:opacity-50 transition-colors"
          >
            {synthLoading === 'pre' ? 'Generating…' : 'Pre-Brief'}
          </button>
          <button
            onClick={() => handleSynth('post')}
            disabled={synthLoading === 'post'}
            className="px-3 py-2 text-sm font-medium bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 transition-colors"
          >
            {synthLoading === 'post' ? 'Generating…' : 'Post-Brief'}
          </button>
        </div>
      </div>

      {synthMsg && (
        <div className={`px-4 py-3 rounded-lg text-sm ${synthMsg.type === 'success' ? 'bg-emerald-50 text-emerald-700' : 'bg-red-50 text-red-700'}`}>
          {synthMsg.text}
        </div>
      )}

      {/* Bloomberg data banner */}
      {showBloombergBanner && (
        <div className="bg-amber-50 border border-amber-200 rounded-xl p-4 flex items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <span className="text-amber-500 text-xl flex-shrink-0">⚠</span>
            <div>
              <div className="text-sm font-semibold text-amber-800">
                {!hasAnyActuals
                  ? 'Financial data not yet uploaded'
                  : 'New earnings available — upload updated model'}
              </div>
              <div className="text-xs text-amber-600 mt-0.5">
                Upload the Bloomberg aggregate analyst model (.xlsx) to populate quarterly revenue, EBIT, EPS estimates and actuals.
              </div>
            </div>
          </div>
          <a
            href="#bloomberg-upload"
            className="shrink-0 px-3 py-1.5 bg-amber-500 hover:bg-amber-600 text-white text-xs font-semibold rounded-lg transition-colors"
          >
            Upload model ↓
          </a>
        </div>
      )}

      {/* Alphie Analyst Research */}
      <AlphieResearch ticker={ticker} />

      {/* Research Panel */}
      <ResearchPanel ticker={ticker} onDone={refreshAll} />

      {/* Bloomberg Model Upload */}
      <div id="bloomberg-upload">
        <BloombergModelUpload ticker={ticker} onDone={refreshAll} />
      </div>

      {/* KPI Trend Chart */}
      {chartData.length > 0 && chartKpis.length > 0 && (
        <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-6">
          <h2 className="text-base font-semibold text-gray-800 mb-4">KPI Trends</h2>
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
              <XAxis dataKey="period" tick={{ fontSize: 11 }} />
              <YAxis tick={{ fontSize: 11 }} width={60} />
              <Tooltip
                contentStyle={{ fontSize: 12, borderRadius: 8, border: '1px solid #e5e7eb' }}
              />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              {chartKpis.map((kpi, i) => (
                <Line
                  key={kpi}
                  type="monotone"
                  dataKey={kpi}
                  name={kpi.replace(/_/g, ' ')}
                  stroke={CHART_COLORS[i % CHART_COLORS.length]}
                  strokeWidth={2}
                  dot={{ r: 3 }}
                  connectNulls
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Latest Brief Card */}
      {latestBrief && (
        <div className="bg-white rounded-xl border border-blue-100 shadow-sm p-6">
          <h2 className="text-base font-semibold text-gray-800 mb-3">
            Latest Brief — {latestEarnings.fiscal_period}
          </h2>
          {latestBrief.post_brief && (
            <p className="text-gray-700 text-sm leading-relaxed mb-4">{latestBrief.post_brief}</p>
          )}
          {latestBrief.consensus_summary && (
            <p className="text-gray-700 text-sm leading-relaxed mb-4">{latestBrief.consensus_summary}</p>
          )}
          {latestBrief.key_highlights?.length > 0 && (
            <ul className="space-y-1">
              {latestBrief.key_highlights.map((h, i) => (
                <li key={i} className="flex items-start gap-2 text-sm text-gray-700">
                  <span className="text-blue-500 mt-0.5 flex-shrink-0">•</span>
                  {h}
                </li>
              ))}
            </ul>
          )}
          <div className="mt-4">
            <Link
              to={`/earnings/${ticker}/${latestEarnings.fiscal_period}`}
              className="text-sm text-blue-600 hover:text-blue-800 font-medium"
            >
              View full brief →
            </Link>
          </div>
        </div>
      )}

      {/* Earnings History Table */}
      <div>
        <h2 className="text-base font-semibold text-gray-800 mb-3">Earnings History</h2>
        <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b border-gray-100">
              <tr>
                <th className="text-left px-4 py-3 font-semibold text-gray-600">Period</th>
                <th className="text-left px-4 py-3 font-semibold text-gray-600">Report Date</th>
                <th className="text-right px-4 py-3 font-semibold text-gray-600">Rev Actual</th>
                <th className="text-right px-4 py-3 font-semibold text-gray-600">Rev Est</th>
                <th className="text-right px-4 py-3 font-semibold text-gray-600">EPS Actual</th>
                <th className="text-right px-4 py-3 font-semibold text-gray-600">EPS Est</th>
                <th className="text-left px-4 py-3 font-semibold text-gray-600">Verdict</th>
                <th className="text-left px-4 py-3 font-semibold text-gray-600">Mgmt</th>
                <th className="text-left px-4 py-3 font-semibold text-gray-600">Guidance</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {earnings.length === 0 ? (
                <tr>
                  <td colSpan={9} className="px-4 py-8 text-center text-gray-400">
                    No earnings data yet. Use the buttons above to generate a brief.
                  </td>
                </tr>
              ) : (
                earnings.map((e) => (
                  <tr key={e.id} className="hover:bg-gray-50 transition-colors">
                    <td className="px-4 py-3">
                      <Link
                        to={`/earnings/${ticker}/${e.fiscal_period}`}
                        className="font-medium text-blue-600 hover:text-blue-800"
                      >
                        {e.fiscal_period}
                      </Link>
                    </td>
                    <td className="px-4 py-3 text-gray-600">{e.report_date || '—'}</td>
                    <td className="px-4 py-3 text-right font-mono text-gray-800">
                      {e.revenue_actual != null ? e.revenue_actual.toLocaleString() : '—'}
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-gray-500">
                      {e.revenue_est != null ? e.revenue_est.toLocaleString() : '—'}
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-gray-800">
                      {e.eps_actual != null ? e.eps_actual.toFixed(2) : '—'}
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-gray-500">
                      {e.eps_est != null ? e.eps_est.toFixed(2) : '—'}
                    </td>
                    <td className="px-4 py-3"><BeatMissBadge value={e.beat_miss} /></td>
                    <td className="px-4 py-3"><ToneBadge value={e.mgmt_tone} type="mgmt" /></td>
                    <td className="px-4 py-3"><ToneBadge value={e.guidance_tone} type="guidance" /></td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
