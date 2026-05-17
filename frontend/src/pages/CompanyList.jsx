import { useEffect, useState, useMemo } from 'react'
import { Link } from 'react-router-dom'
import { getCompanies, getRecentEarnings } from '../api/index'

function BeatMissBadge({ value }) {
  if (!value) return <span className="text-gray-300 text-xs">—</span>
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

export default function CompanyList() {
  const [companies, setCompanies] = useState([])
  const [latestEarnings, setLatestEarnings] = useState({})
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [sortField, setSortField] = useState('ticker')
  const [sortDir, setSortDir] = useState('asc')

  useEffect(() => {
    Promise.all([getCompanies(), getRecentEarnings()])
      .then(([companies, recent]) => {
        setCompanies(companies)
        // Build latest earnings map by ticker
        const map = {}
        recent.forEach((e) => {
          if (!map[e.ticker] || e.report_date > map[e.ticker].report_date) {
            map[e.ticker] = e
          }
        })
        setLatestEarnings(map)
      })
      .finally(() => setLoading(false))
  }, [])

  const handleSort = (field) => {
    if (sortField === field) {
      setSortDir(sortDir === 'asc' ? 'desc' : 'asc')
    } else {
      setSortField(field)
      setSortDir('asc')
    }
  }

  const filtered = useMemo(() => {
    const q = search.toLowerCase()
    return companies.filter(
      (c) =>
        c.ticker.toLowerCase().includes(q) ||
        c.name.toLowerCase().includes(q) ||
        (c.sector || '').toLowerCase().includes(q) ||
        (c.country || '').toLowerCase().includes(q)
    )
  }, [companies, search])

  const sorted = useMemo(() => {
    return [...filtered].sort((a, b) => {
      let av, bv
      if (sortField === 'last_report') {
        av = latestEarnings[a.ticker]?.report_date || ''
        bv = latestEarnings[b.ticker]?.report_date || ''
      } else if (sortField === 'beat_miss') {
        av = latestEarnings[a.ticker]?.beat_miss || ''
        bv = latestEarnings[b.ticker]?.beat_miss || ''
      } else {
        av = (a[sortField] || '').toString().toLowerCase()
        bv = (b[sortField] || '').toString().toLowerCase()
      }
      if (av < bv) return sortDir === 'asc' ? -1 : 1
      if (av > bv) return sortDir === 'asc' ? 1 : -1
      return 0
    })
  }, [filtered, sortField, sortDir, latestEarnings])

  const SortIcon = ({ field }) => {
    if (sortField !== field) return <span className="text-gray-300 ml-1">↕</span>
    return <span className="text-blue-500 ml-1">{sortDir === 'asc' ? '↑' : '↓'}</span>
  }

  const ThBtn = ({ field, children }) => (
    <th
      className="text-left px-4 py-3 font-semibold text-gray-600 cursor-pointer hover:text-gray-900 select-none"
      onClick={() => handleSort(field)}
    >
      {children}
      <SortIcon field={field} />
    </th>
  )

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64 text-gray-400">
        Loading companies…
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Companies</h1>
          <p className="text-gray-500 mt-1">{companies.length} companies on platform</p>
        </div>
        <Link
          to="/companies/new"
          className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 transition-colors"
        >
          + Add Company
        </Link>
      </div>

      {/* Search */}
      <div className="relative">
        <input
          type="text"
          placeholder="Search by ticker, name, sector, or country…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="w-full px-4 py-2.5 pl-10 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
        />
        <svg className="absolute left-3 top-3 w-4 h-4 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
        </svg>
      </div>

      {/* Table */}
      <div className="bg-white rounded-xl border border-gray-100 overflow-hidden shadow-sm">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b border-gray-100">
            <tr>
              <ThBtn field="ticker">Ticker</ThBtn>
              <ThBtn field="name">Name</ThBtn>
              <ThBtn field="sector">Sector</ThBtn>
              <ThBtn field="country">Country</ThBtn>
              <ThBtn field="exchange">Exchange</ThBtn>
              <ThBtn field="last_report">Last Report</ThBtn>
              <ThBtn field="beat_miss">Result</ThBtn>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            {sorted.length === 0 ? (
              <tr>
                <td colSpan={7} className="px-4 py-8 text-center text-gray-400">
                  No companies match your search.
                </td>
              </tr>
            ) : (
              sorted.map((company) => {
                const latest = latestEarnings[company.ticker]
                return (
                  <tr
                    key={company.ticker}
                    className="hover:bg-gray-50 transition-colors cursor-pointer"
                  >
                    <td className="px-4 py-3">
                      <Link
                        to={`/companies/${company.ticker}`}
                        className="font-bold text-blue-600 hover:text-blue-800 font-mono"
                      >
                        {company.ticker}
                      </Link>
                    </td>
                    <td className="px-4 py-3 font-medium text-gray-900">
                      <Link to={`/companies/${company.ticker}`} className="hover:text-blue-600">
                        {company.name}
                      </Link>
                    </td>
                    <td className="px-4 py-3">
                      {company.sector && (
                        <span className="px-2 py-0.5 bg-purple-50 text-purple-700 rounded text-xs font-medium">
                          {company.sector}
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-gray-600">
                      <span className="flex items-center gap-1">
                        {company.country}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-gray-500 text-xs font-mono">{company.exchange}</td>
                    <td className="px-4 py-3 text-gray-600">
                      {latest?.report_date || <span className="text-gray-300">—</span>}
                    </td>
                    <td className="px-4 py-3">
                      <BeatMissBadge value={latest?.beat_miss} />
                    </td>
                  </tr>
                )
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
