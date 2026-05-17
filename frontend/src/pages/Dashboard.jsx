import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { getCalendar, getRecentEarnings, getEarningsTrends, triggerPostBrief } from '../api/index'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function BeatMissBadge({ value }) {
  if (!value) return <span className="text-gray-300 text-xs">—</span>
  const styles = {
    beat:    'bg-emerald-100 text-emerald-700 border border-emerald-200',
    miss:    'bg-red-100 text-red-700 border border-red-200',
    in_line: 'bg-amber-100 text-amber-700 border border-amber-200',
  }
  const labels = { beat: 'Beat', miss: 'Miss', in_line: 'In Line' }
  return (
    <span className={`px-2 py-0.5 rounded text-xs font-semibold ${styles[value] || 'bg-gray-100 text-gray-600'}`}>
      {labels[value] || value}
    </span>
  )
}

function GuidanceBadge({ value }) {
  if (!value) return null
  const styles = {
    raised:     'text-emerald-600 bg-emerald-50 border-emerald-200',
    maintained: 'text-gray-600 bg-gray-50 border-gray-200',
    lowered:    'text-red-600 bg-red-50 border-red-200',
    withdrawn:  'text-amber-600 bg-amber-50 border-amber-200',
  }
  const icons = { raised: '↑', maintained: '→', lowered: '↓', withdrawn: '⚠' }
  return (
    <span className={`px-2 py-0.5 rounded border text-xs font-medium ${styles[value] || 'text-gray-600 bg-gray-50 border-gray-200'}`}>
      {icons[value]} {value.charAt(0).toUpperCase() + value.slice(1)}
    </span>
  )
}

function fmtRevenue(v) {
  if (v == null) return null
  return v >= 1000 ? `€${(v / 1000).toFixed(1)}bn` : `€${Math.round(v)}m`
}

function fmtDate(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })
}

function dayLabel(iso) {
  const d = new Date(iso)
  const today = new Date()
  const diff = Math.round((d - today) / 86400000)
  if (diff === 0) return 'Today'
  if (diff === 1) return 'Tomorrow'
  return d.toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' })
}

// ---------------------------------------------------------------------------
// Needs Attention
// ---------------------------------------------------------------------------

function NeedsAttention({ recent, onBriefGenerated }) {
  const [generating, setGenerating] = useState({})

  const items = recent.filter((e) => {
    const hasActuals = e.revenue_actual != null || e.eps_actual != null
    const pb = e.post_brief || {}
    const hasBrief = pb.post_brief != null
    return hasActuals && !hasBrief
  })

  if (!items.length) return null

  const generate = async (ticker) => {
    setGenerating((g) => ({ ...g, [ticker]: true }))
    try {
      await triggerPostBrief(ticker)
      onBriefGenerated()
    } catch {}
    setGenerating((g) => ({ ...g, [ticker]: false }))
  }

  return (
    <div className="bg-amber-50 border border-amber-200 rounded-xl p-4">
      <div className="flex items-center gap-2 mb-3">
        <svg className="w-4 h-4 text-amber-600 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
        </svg>
        <span className="text-sm font-semibold text-amber-800">
          Needs Brief · {items.length} {items.length === 1 ? 'report' : 'reports'} with actuals but no brief yet
        </span>
      </div>
      <div className="space-y-2">
        {items.map((e) => (
          <div key={e.id} className="flex items-center justify-between gap-3 bg-white rounded-lg px-3 py-2 border border-amber-100">
            <div className="flex items-center gap-2 min-w-0">
              <Link to={`/companies/${e.ticker}`} className="font-bold text-gray-800 hover:text-blue-600 text-sm shrink-0">
                {e.ticker}
              </Link>
              <span className="text-xs text-gray-400 bg-gray-50 px-1.5 py-0.5 rounded">{e.fiscal_period}</span>
              {fmtRevenue(e.revenue_actual) && (
                <span className="text-xs text-gray-500 hidden sm:inline">{fmtRevenue(e.revenue_actual)} rev</span>
              )}
            </div>
            <button
              onClick={() => generate(e.ticker)}
              disabled={generating[e.ticker]}
              className="text-xs font-semibold text-indigo-600 hover:text-indigo-800 disabled:opacity-40 whitespace-nowrap shrink-0"
            >
              {generating[e.ticker] ? 'Generating…' : 'Generate Brief →'}
            </button>
          </div>
        ))}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Upcoming calendar — compact date-grouped list
// ---------------------------------------------------------------------------

function UpcomingCalendar({ calendar }) {
  const today = new Date()
  const todayKey = today.toISOString().split('T')[0]

  const upcoming = calendar
    .filter((e) => e.report_date && e.report_date > todayKey)
    .sort((a, b) => a.report_date.localeCompare(b.report_date))

  if (!upcoming.length) return (
    <div className="text-xs text-gray-400">No upcoming earnings in the next 14 days.</div>
  )

  // Group by date
  const grouped = {}
  upcoming.forEach((e) => {
    if (!grouped[e.report_date]) grouped[e.report_date] = []
    grouped[e.report_date].push(e)
  })

  return (
    <div className="space-y-2">
      {Object.entries(grouped).map(([date, entries]) => (
        <div key={date} className="flex gap-3 items-start">
          <div className="w-28 shrink-0 pt-1">
            <span className="text-xs font-semibold text-gray-500">{dayLabel(date)}</span>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {entries.map((e) => (
              <Link
                key={e.ticker}
                to={`/companies/${e.ticker}`}
                className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-semibold border transition-colors hover:opacity-80 ${
                  e.is_watchlist
                    ? 'bg-blue-100 border-blue-200 text-blue-800'
                    : 'bg-gray-50 border-gray-200 text-gray-700'
                }`}
              >
                {e.ticker}
                {e.is_watchlist && <span className="text-blue-400">★</span>}
              </Link>
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Recent report card
// ---------------------------------------------------------------------------

function ReportCard({ entry }) {
  const pb = (() => {
    try {
      if (!entry.post_brief) return {}
      return typeof entry.post_brief === 'string' ? JSON.parse(entry.post_brief) : entry.post_brief
    } catch { return {} }
  })()

  const highlight = (entry.key_highlights?.[0]) || pb.key_highlights?.[0]
  const revenue = entry.revenue_actual ?? pb.revenue_actual
  const ebitMargin = pb.ebit_margin_pct
  const hasBrief = !!pb.post_brief

  return (
    <div className={`bg-white rounded-xl border p-4 flex flex-col hover:shadow-sm transition-shadow ${
      entry.beat_miss === 'miss' ? 'border-red-100' :
      entry.beat_miss === 'beat' ? 'border-emerald-100' : 'border-gray-100'
    }`}>
      <div className="flex items-start justify-between gap-2 mb-2">
        <div>
          <div className="flex items-center gap-2">
            <Link to={`/companies/${entry.ticker}`} className="font-bold text-gray-900 hover:text-blue-600">
              {entry.ticker}
            </Link>
            <span className="text-xs text-gray-400 bg-gray-50 px-1.5 py-0.5 rounded">{entry.fiscal_period}</span>
          </div>
          <div className="flex items-center gap-1.5 mt-1.5 flex-wrap">
            <BeatMissBadge value={entry.beat_miss} />
            <GuidanceBadge value={entry.guidance_tone} />
          </div>
        </div>
        <div className="text-right shrink-0">
          {revenue != null && <div className="text-xs font-medium text-gray-700">{fmtRevenue(revenue)}</div>}
          {ebitMargin != null && (
            <div className={`text-xs font-medium ${ebitMargin >= 15 ? 'text-emerald-600' : ebitMargin >= 8 ? 'text-gray-500' : 'text-amber-600'}`}>
              {ebitMargin.toFixed(1)}% EBIT
            </div>
          )}
        </div>
      </div>

      {highlight && (
        <p className="text-xs text-gray-500 line-clamp-2 leading-relaxed flex-1 mb-3">{highlight}</p>
      )}

      <div className="flex items-center justify-between pt-2 border-t border-gray-50 mt-auto">
        <span className="text-xs text-gray-400">{fmtDate(entry.report_date)}</span>
        {hasBrief ? (
          <Link to={`/earnings/${entry.ticker}/${entry.fiscal_period}`} className="text-xs font-semibold text-blue-600 hover:text-blue-800">
            Open Brief →
          </Link>
        ) : (
          <span className="text-xs text-amber-500 font-medium">No brief yet</span>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Dashboard
// ---------------------------------------------------------------------------

export default function Dashboard() {
  const [calendar, setCalendar] = useState([])
  const [recent, setRecent] = useState([])
  const [loadingCal, setLoadingCal] = useState(true)
  const [loadingRecent, setLoadingRecent] = useState(true)

  const load = () => {
    getCalendar(14).then(setCalendar).finally(() => setLoadingCal(false))
    getRecentEarnings().then(setRecent).finally(() => setLoadingRecent(false))
  }

  useEffect(load, [])

  const today = new Date()
  const todayStr = today.toISOString().split('T')[0]
  const sevenDaysAgo = new Date(today); sevenDaysAgo.setDate(today.getDate() - 7)

  // Only show past reports — future-dated entries belong in the upcoming calendar
  const pastReports = recent.filter((e) => e.report_date && e.report_date <= todayStr)
  const lastWeek = pastReports.filter((e) => new Date(e.report_date) >= sevenDaysAgo)
  const older = pastReports.filter((e) => new Date(e.report_date) < sevenDaysAgo)

  const loading = loadingCal || loadingRecent

  return (
    <div className="space-y-7">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Dashboard</h1>
        <p className="text-gray-400 text-sm mt-1">Morning briefing — earnings calendar, recent results, and action queue</p>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-20">
          <div className="w-6 h-6 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin" />
        </div>
      ) : (
        <>
          {/* Needs attention */}
          <NeedsAttention recent={recent} onBriefGenerated={load} />

          {/* Two-column: upcoming + last 7 days */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Upcoming */}
            <div>
              <h2 className="text-sm font-semibold text-gray-700 mb-3 flex items-center gap-2">
                Upcoming
                <span className="text-xs font-normal text-gray-400">next 14 days</span>
              </h2>
              <UpcomingCalendar calendar={calendar} />
              <div className="flex gap-3 mt-3 text-xs text-gray-400">
                <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 rounded bg-blue-100 inline-block" /> Watchlist</span>
                <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 rounded bg-gray-100 inline-block" /> Platform</span>
              </div>
            </div>

            {/* Last 7 days */}
            <div>
              <h2 className="text-sm font-semibold text-gray-700 mb-3 flex items-center gap-2">
                Just Reported
                <span className="text-xs font-normal text-gray-400">last 7 days · {lastWeek.length} result{lastWeek.length !== 1 ? 's' : ''}</span>
              </h2>
              {lastWeek.length === 0 ? (
                <div className="text-xs text-gray-400">No reports in the last 7 days.</div>
              ) : (
                <div className="space-y-3">
                  {lastWeek.map((e) => <ReportCard key={e.id} entry={e} />)}
                </div>
              )}
            </div>
          </div>

          {/* Older reports */}
          {older.length > 0 && (
            <div>
              <h2 className="text-sm font-semibold text-gray-700 mb-3 flex items-center gap-2">
                Older Reports
                <span className="text-xs font-normal text-gray-400">8–30 days ago · {older.length} results</span>
              </h2>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                {older.map((e) => <ReportCard key={e.id} entry={e} />)}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
