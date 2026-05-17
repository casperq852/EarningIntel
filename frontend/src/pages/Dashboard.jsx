import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { LineChart, Line, ResponsiveContainer, Tooltip } from 'recharts'
import { getCalendar, getRecentEarnings, getEarningsTrends } from '../api/index'

const DAYS_OF_WEEK = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']

// ---------------------------------------------------------------------------
// Shared badge / display helpers
// ---------------------------------------------------------------------------

function BeatMissBadge({ value }) {
  if (!value) return <span className="text-gray-400 text-xs">—</span>
  const styles = {
    beat: 'bg-emerald-100 text-emerald-700 border border-emerald-200',
    miss: 'bg-red-100 text-red-700 border border-red-200',
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
    raised: 'text-emerald-600 bg-emerald-50 border-emerald-200',
    maintained: 'text-gray-600 bg-gray-50 border-gray-200',
    lowered: 'text-red-600 bg-red-50 border-red-200',
    withdrawn: 'text-amber-600 bg-amber-50 border-amber-200',
  }
  const icons = { raised: '↑', maintained: '→', lowered: '↓', withdrawn: '⚠' }
  const label = value.charAt(0).toUpperCase() + value.slice(1)
  return (
    <span className={`px-2 py-0.5 rounded border text-xs font-medium ${styles[value] || 'text-gray-600 bg-gray-50 border-gray-200'}`}>
      {icons[value]} {label}
    </span>
  )
}

// ---------------------------------------------------------------------------
// Mini sparkline (Recharts)
// ---------------------------------------------------------------------------

function RevenueSparkline({ data }) {
  if (!data || data.length < 2) return <span className="text-gray-300 text-xs">—</span>
  const points = data.filter((d) => d.revenue != null)
  if (points.length < 2) return <span className="text-gray-300 text-xs">—</span>

  const first = points[0].revenue
  const last = points[points.length - 1].revenue
  const color = last >= first ? '#10b981' : '#ef4444'

  return (
    <ResponsiveContainer width={72} height={28}>
      <LineChart data={points} margin={{ top: 2, bottom: 2, left: 0, right: 0 }}>
        <Line
          type="monotone"
          dataKey="revenue"
          stroke={color}
          strokeWidth={1.5}
          dot={false}
          isAnimationActive={false}
        />
        <Tooltip
          formatter={(v) => [`€${(v / 1000).toFixed(1)}bn`, 'Rev']}
          labelFormatter={(_, payload) => payload?.[0]?.payload?.fiscal_period || ''}
          contentStyle={{ fontSize: 10, padding: '2px 6px' }}
        />
      </LineChart>
    </ResponsiveContainer>
  )
}

// ---------------------------------------------------------------------------
// Reporting Today strip
// ---------------------------------------------------------------------------

function ReportingTodayStrip({ entries }) {
  const todayKey = new Date().toISOString().split('T')[0]
  const today = entries.filter((e) => e.report_date === todayKey)
  if (today.length === 0) return null

  return (
    <div className="mb-2 bg-blue-50 border border-blue-200 rounded-xl p-4">
      <div className="flex items-center gap-2 mb-3">
        <span className="w-2 h-2 bg-blue-500 rounded-full animate-pulse" />
        <span className="text-sm font-semibold text-blue-800">Reporting Today</span>
        <span className="text-xs text-blue-500">({today.length} compan{today.length === 1 ? 'y' : 'ies'})</span>
      </div>
      <div className="flex flex-wrap gap-2">
        {today.map((e) => (
          <Link
            key={e.ticker}
            to={`/companies/${e.ticker}`}
            className={`flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium border transition-colors hover:bg-white ${
              e.is_watchlist
                ? 'bg-blue-100 border-blue-300 text-blue-800'
                : 'bg-white border-blue-200 text-blue-700'
            }`}
          >
            <span className="font-bold">{e.ticker}</span>
            {e.company_name && <span className="text-xs text-blue-500 hidden sm:inline">{e.company_name}</span>}
            {e.is_watchlist && <span className="text-blue-400">★</span>}
          </Link>
        ))}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Rich earnings feed card
// ---------------------------------------------------------------------------

function EarningsCard({ entry, trend }) {
  const pb = (() => {
    try {
      if (!entry.post_brief) return {}
      return typeof entry.post_brief === 'string' ? JSON.parse(entry.post_brief) : entry.post_brief
    } catch { return {} }
  })()

  const highlights = entry.key_highlights?.length ? entry.key_highlights : (pb.key_highlights || [])
  const revenue = entry.revenue_actual ?? pb.revenue_actual
  const ebitMargin = pb.ebit_margin_pct
  const isMiss = entry.beat_miss === 'miss'
  const isBeat = entry.beat_miss === 'beat'

  return (
    <div className={`bg-white rounded-xl border p-4 hover:shadow-md transition-shadow flex flex-col ${
      isMiss ? 'border-red-100' : isBeat ? 'border-emerald-100' : 'border-gray-100'
    }`}>
      {/* Header row */}
      <div className="flex items-start justify-between gap-3 mb-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <Link to={`/companies/${entry.ticker}`} className="font-bold text-gray-900 hover:text-blue-600 text-base">
              {entry.ticker}
            </Link>
            <span className="text-xs text-gray-400 font-medium bg-gray-50 px-1.5 py-0.5 rounded">
              {entry.fiscal_period}
            </span>
          </div>
          <div className="flex items-center gap-2 mt-1.5 flex-wrap">
            <BeatMissBadge value={entry.beat_miss} />
            <GuidanceBadge value={entry.guidance_tone} />
          </div>
        </div>
        {/* Sparkline + revenue */}
        <div className="flex flex-col items-end gap-0.5 shrink-0">
          <RevenueSparkline data={trend} />
          {revenue != null && (
            <span className="text-xs text-gray-500 tabular-nums">
              €{revenue >= 1000 ? `${(revenue / 1000).toFixed(1)}bn` : `${revenue.toFixed(0)}m`}
            </span>
          )}
          {ebitMargin != null && (
            <span className={`text-xs font-medium tabular-nums ${ebitMargin >= 15 ? 'text-emerald-600' : ebitMargin >= 8 ? 'text-gray-500' : 'text-amber-600'}`}>
              {ebitMargin.toFixed(1)}% EBIT
            </span>
          )}
        </div>
      </div>

      {/* Top highlight */}
      {highlights[0] && (
        <p className="text-xs text-gray-600 line-clamp-2 mb-3 leading-relaxed flex-1">
          {highlights[0]}
        </p>
      )}

      {/* Footer */}
      <div className="flex items-center justify-between mt-auto pt-2 border-t border-gray-50">
        <span className="text-xs text-gray-400">{entry.report_date || ''}</span>
        <Link
          to={`/earnings/${entry.ticker}/${entry.fiscal_period}`}
          className="text-xs font-semibold text-blue-600 hover:text-blue-800 transition-colors"
        >
          Open Analysis →
        </Link>
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
  const [trends, setTrends] = useState({})
  const [loadingCal, setLoadingCal] = useState(true)
  const [loadingRecent, setLoadingRecent] = useState(true)
  const [calError, setCalError] = useState(null)

  useEffect(() => {
    getCalendar(14)
      .then(setCalendar)
      .catch((e) => setCalError(e.message))
      .finally(() => setLoadingCal(false))

    getRecentEarnings()
      .then((data) => {
        setRecent(data)
        const tickers = [...new Set(data.map((e) => e.ticker))]
        if (tickers.length > 0) {
          getEarningsTrends(tickers, 5).then(setTrends).catch(() => {})
        }
      })
      .finally(() => setLoadingRecent(false))
  }, [])

  const sevenDaysAgo = new Date()
  sevenDaysAgo.setDate(sevenDaysAgo.getDate() - 7)
  const weekRecent = recent.filter((e) => e.report_date && new Date(e.report_date) >= sevenDaysAgo)
  const weekBeats = weekRecent.filter((e) => e.beat_miss === 'beat').length
  const weekMisses = weekRecent.filter((e) => e.beat_miss === 'miss').length
  const weekInLine = weekRecent.filter((e) => e.beat_miss === 'in_line').length

  const today = new Date()
  const todayKey = today.toISOString().split('T')[0]
  const days = Array.from({ length: 14 }, (_, i) => {
    const d = new Date(today)
    d.setDate(today.getDate() + i)
    return d
  })

  const calendarByDate = {}
  calendar.forEach((entry) => {
    if (!calendarByDate[entry.report_date]) calendarByDate[entry.report_date] = []
    calendarByDate[entry.report_date].push(entry)
  })

  const upcomingWatchlist = calendar.filter((e) => {
    if (!e.report_date || !e.is_watchlist) return false
    const diff = Math.round((new Date(e.report_date) - today) / 86400000)
    return diff > 0 && diff <= 7
  })

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Dashboard</h1>
        <p className="text-gray-500 mt-1">Earnings calendar, recent results, and portfolio watchlist</p>
      </div>

      {/* Reporting Today strip */}
      {!loadingCal && <ReportingTodayStrip entries={calendar} />}

      {/* Watchlist upcoming this week */}
      {upcomingWatchlist.length > 0 && (
        <div className="bg-amber-50 border border-amber-200 rounded-xl p-4">
          <div className="flex items-center gap-2 mb-3">
            <span className="text-sm font-semibold text-amber-800">★ Watchlist — Reporting This Week</span>
          </div>
          <div className="flex flex-wrap gap-2">
            {upcomingWatchlist.map((e) => (
              <Link
                key={`${e.ticker}-${e.report_date}`}
                to={`/companies/${e.ticker}`}
                className="flex items-center gap-2 px-3 py-2 rounded-lg bg-white border border-amber-200 text-sm font-medium text-amber-900 hover:bg-amber-100 transition-colors"
              >
                <span className="font-bold">{e.ticker}</span>
                <span className="text-xs text-amber-500">{e.report_date}</span>
              </Link>
            ))}
          </div>
        </div>
      )}

      {/* Week Stats */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        {[
          { label: 'Reports This Week', value: weekRecent.length, color: 'bg-blue-50 text-blue-700' },
          { label: 'Beats', value: weekBeats, color: 'bg-emerald-50 text-emerald-700' },
          { label: 'Misses', value: weekMisses, color: 'bg-red-50 text-red-700' },
          { label: 'In Line', value: weekInLine, color: 'bg-amber-50 text-amber-700' },
        ].map((stat) => (
          <div key={stat.label} className={`rounded-xl p-4 ${stat.color}`}>
            <div className="text-3xl font-bold">{stat.value}</div>
            <div className="text-sm font-medium mt-1 opacity-80">{stat.label}</div>
          </div>
        ))}
      </div>

      {/* Recent Reports Feed */}
      <div>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-gray-800">Recent Reports</h2>
          <span className="text-xs text-gray-400">Last 30 days · {recent.length} result{recent.length !== 1 ? 's' : ''}</span>
        </div>
        {loadingRecent ? (
          <div className="text-gray-500 text-sm">Loading…</div>
        ) : recent.length === 0 ? (
          <div className="text-gray-400 text-sm">No earnings reported recently.</div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {recent.map((e) => (
              <EarningsCard key={e.id} entry={e} trend={trends[e.ticker]} />
            ))}
          </div>
        )}
      </div>

      {/* 14-Day Calendar Grid */}
      <div>
        <h2 className="text-lg font-semibold text-gray-800 mb-3">14-Day Earnings Calendar</h2>
        {loadingCal ? (
          <div className="text-gray-500 text-sm">Loading calendar…</div>
        ) : calError ? (
          <div className="text-red-500 text-sm">Could not load calendar: {calError}</div>
        ) : (
          <div className="grid grid-cols-7 gap-2">
            {DAYS_OF_WEEK.map((d) => (
              <div key={d} className="text-xs font-semibold text-gray-400 text-center pb-1">{d}</div>
            ))}
            {Array.from({ length: days[0].getDay() }, (_, i) => (
              <div key={`empty-${i}`} />
            ))}
            {days.map((day) => {
              const key = day.toISOString().split('T')[0]
              const entries = calendarByDate[key] || []
              const isToday = key === todayKey
              return (
                <div
                  key={key}
                  className={`rounded-lg border p-2 min-h-[80px] ${
                    isToday ? 'border-blue-400 bg-blue-50' : 'border-gray-100 bg-white'
                  }`}
                >
                  <div className={`text-xs font-semibold mb-1 ${isToday ? 'text-blue-600' : 'text-gray-500'}`}>
                    {day.getDate()}
                  </div>
                  <div className="space-y-0.5">
                    {entries.slice(0, 4).map((entry) => (
                      <Link
                        key={entry.ticker}
                        to={`/companies/${entry.ticker}`}
                        className={`block text-xs truncate rounded px-1 py-0.5 font-medium ${
                          entry.is_watchlist
                            ? 'bg-blue-100 text-blue-700'
                            : entry.on_platform
                            ? 'bg-gray-100 text-gray-700'
                            : 'text-gray-500'
                        }`}
                      >
                        {entry.ticker}
                      </Link>
                    ))}
                    {entries.length > 4 && (
                      <div className="text-xs text-gray-400">+{entries.length - 4} more</div>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        )}
        <div className="flex gap-4 mt-2 text-xs text-gray-500">
          <span className="flex items-center gap-1"><span className="w-3 h-3 rounded bg-blue-100 inline-block" /> Watchlist</span>
          <span className="flex items-center gap-1"><span className="w-3 h-3 rounded bg-gray-100 inline-block" /> Platform company</span>
        </div>
      </div>
    </div>
  )
}
