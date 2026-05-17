import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { getWatchlist, addToWatchlist, removeFromWatchlist, updateWatchlistPrefs, updateAlertConditions, getCompanies } from '../api/index'
import { useEmail } from '../hooks/useEmail'

function Toggle({ checked, onChange, label }) {
  return (
    <button
      type="button"
      onClick={() => onChange(!checked)}
      className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors focus:outline-none ${
        checked ? 'bg-blue-500' : 'bg-gray-200'
      }`}
      title={label}
    >
      <span
        className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white shadow transition-transform ${
          checked ? 'translate-x-5' : 'translate-x-1'
        }`}
      />
    </button>
  )
}

function AlertConditionChips({ entry, onChange }) {
  const cond = entry.alert_conditions || {}
  const notifyOn = cond.notify_on
  const guidanceCut = cond.guidance_cut_only

  let filterLabel = 'Always'
  let filterStyle = 'bg-gray-100 text-gray-600 border-gray-200'
  if (notifyOn && JSON.stringify(notifyOn) === JSON.stringify(['miss'])) {
    filterLabel = 'Miss only'
    filterStyle = 'bg-red-50 text-red-600 border-red-200'
  } else if (notifyOn) {
    filterLabel = 'Miss + In Line'
    filterStyle = 'bg-amber-50 text-amber-600 border-amber-200'
  }

  return (
    <div className="flex flex-wrap gap-1.5">
      <button
        onClick={() => onChange(entry, 'notify_on')}
        title="Click to cycle: Always → Miss only → Miss + In Line"
        className={`px-2 py-0.5 rounded border text-xs font-medium transition-colors hover:opacity-80 ${filterStyle}`}
      >
        {filterLabel}
      </button>
      <button
        onClick={() => onChange(entry, 'guidance_cut')}
        title="Also alert on guidance cuts"
        className={`px-2 py-0.5 rounded border text-xs font-medium transition-colors hover:opacity-80 ${
          guidanceCut ? 'bg-amber-50 text-amber-600 border-amber-200' : 'bg-gray-50 text-gray-400 border-gray-200'
        }`}
      >
        ↓ Guidance
      </button>
    </div>
  )
}

export default function Watchlist() {
  const { email, setEmail } = useEmail()
  const [tempEmail, setTempEmail] = useState(email)
  const [watchlist, setWatchlist] = useState([])
  const [allCompanies, setAllCompanies] = useState([])
  const [loading, setLoading] = useState(false)
  const [addTicker, setAddTicker] = useState('')
  const [addError, setAddError] = useState(null)
  const [addSuccess, setAddSuccess] = useState(null)

  const load = (emailAddr) => {
    if (!emailAddr) return
    setLoading(true)
    getWatchlist(emailAddr)
      .then(setWatchlist)
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    getCompanies().then(setAllCompanies)
    if (email) load(email)
  }, [email])

  const handleEmailSubmit = (e) => {
    e.preventDefault()
    setEmail(tempEmail.trim().toLowerCase())
    load(tempEmail.trim().toLowerCase())
  }

  const handleAdd = async () => {
    setAddError(null)
    setAddSuccess(null)
    const ticker = addTicker.trim().toUpperCase()
    if (!ticker) return
    try {
      const entry = await addToWatchlist(email, ticker)
      setWatchlist((prev) => [entry, ...prev])
      setAddTicker('')
      setAddSuccess(`${ticker} added to watchlist.`)
    } catch (e) {
      setAddError(e.message)
    }
  }

  const handleRemove = async (ticker) => {
    try {
      await removeFromWatchlist(email, ticker)
      setWatchlist((prev) => prev.filter((e) => e.ticker !== ticker))
    } catch (e) {
      // silently ignore or show toast
    }
  }

  const handleToggle = async (entry, field, value) => {
    try {
      const prefs = { [field]: value }
      const updated = await updateWatchlistPrefs(email, entry.ticker, prefs)
      setWatchlist((prev) => prev.map((e) => (e.ticker === entry.ticker ? updated : e)))
    } catch (e) {
      // ignore
    }
  }

  const handleAlertCondition = async (entry, condition) => {
    // Cycle through: always → miss_only → guidance_cut → always
    const current = entry.alert_conditions || {}
    let next = {}
    if (condition === 'notify_on') {
      const cur = current.notify_on
      if (!cur) next = { notify_on: ['miss'] }
      else if (JSON.stringify(cur) === JSON.stringify(['miss'])) next = { notify_on: ['miss', 'in_line'] }
      else next = {}
    } else if (condition === 'guidance_cut') {
      next = current.guidance_cut_only ? {} : { ...current, guidance_cut_only: true }
    }
    try {
      const updated = await updateAlertConditions(email, entry.ticker, next)
      setWatchlist((prev) => prev.map((e) => (e.ticker === entry.ticker ? updated : e)))
    } catch (e) {
      // ignore
    }
  }

  if (!email) {
    return (
      <div className="max-w-md mx-auto mt-16">
        <h1 className="text-2xl font-bold text-gray-900 mb-2">Watchlist</h1>
        <p className="text-gray-500 mb-6 text-sm">
          Enter your email address to access your personal watchlist.
        </p>
        <form onSubmit={handleEmailSubmit} className="space-y-3">
          <input
            type="email"
            required
            value={tempEmail}
            onChange={(e) => setTempEmail(e.target.value)}
            placeholder="you@example.com"
            className="w-full px-4 py-2.5 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          <button
            type="submit"
            className="w-full px-4 py-2.5 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700"
          >
            Continue
          </button>
        </form>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Watchlist</h1>
          <p className="text-gray-500 mt-1 text-sm">{email}</p>
        </div>
        <button
          onClick={() => setEmail('')}
          className="text-xs text-gray-400 hover:text-gray-600"
        >
          Switch account
        </button>
      </div>

      {/* Add Company */}
      <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-4">
        <div className="text-sm font-semibold text-gray-700 mb-3">Add Company</div>
        <div className="flex gap-2">
          <input
            type="text"
            value={addTicker}
            onChange={(e) => setAddTicker(e.target.value.toUpperCase())}
            onKeyDown={(e) => e.key === 'Enter' && handleAdd()}
            placeholder="Ticker (e.g. AAPL)"
            list="company-tickers"
            className="flex-1 px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 font-mono"
          />
          <datalist id="company-tickers">
            {allCompanies.map((c) => (
              <option key={c.ticker} value={c.ticker}>{c.name}</option>
            ))}
          </datalist>
          <button
            onClick={handleAdd}
            className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700"
          >
            Add
          </button>
        </div>
        {addError && <p className="text-red-500 text-xs mt-2">{addError}</p>}
        {addSuccess && <p className="text-emerald-600 text-xs mt-2">{addSuccess}</p>}
      </div>

      {/* Watchlist Table */}
      {loading ? (
        <div className="text-gray-400 text-sm">Loading watchlist…</div>
      ) : watchlist.length === 0 ? (
        <div className="text-center py-12 text-gray-400">
          <div className="text-4xl mb-3">📋</div>
          <div>Your watchlist is empty. Add a company above.</div>
        </div>
      ) : (
        <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b border-gray-100">
              <tr>
                <th className="text-left px-4 py-3 font-semibold text-gray-600">Ticker</th>
                <th className="text-left px-4 py-3 font-semibold text-gray-600">Company</th>
                <th className="text-left px-4 py-3 font-semibold text-gray-600">Sector</th>
                <th className="text-center px-4 py-3 font-semibold text-gray-600">Pre-Brief</th>
                <th className="text-center px-4 py-3 font-semibold text-gray-600">Post-Brief</th>
                <th className="text-left px-4 py-3 font-semibold text-gray-600">Alert Filter</th>
                <th className="text-left px-4 py-3 font-semibold text-gray-600">Added</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {watchlist.map((entry) => (
                <tr key={entry.ticker} className="hover:bg-gray-50 transition-colors">
                  <td className="px-4 py-3">
                    <Link
                      to={`/companies/${entry.ticker}`}
                      className="font-bold text-blue-600 hover:text-blue-800 font-mono"
                    >
                      {entry.ticker}
                    </Link>
                  </td>
                  <td className="px-4 py-3 font-medium text-gray-800">
                    {entry.company?.name || '—'}
                  </td>
                  <td className="px-4 py-3 text-gray-500">
                    {entry.company?.sector || '—'}
                  </td>
                  <td className="px-4 py-3 text-center">
                    <div className="flex justify-center">
                      <Toggle
                        checked={entry.notify_pre_brief}
                        onChange={(val) => handleToggle(entry, 'notify_pre_brief', val)}
                        label="Pre-Brief Alerts"
                      />
                    </div>
                  </td>
                  <td className="px-4 py-3 text-center">
                    <div className="flex justify-center">
                      <Toggle
                        checked={entry.notify_post_brief}
                        onChange={(val) => handleToggle(entry, 'notify_post_brief', val)}
                        label="Post-Brief Alerts"
                      />
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <AlertConditionChips entry={entry} onChange={handleAlertCondition} />
                  </td>
                  <td className="px-4 py-3 text-gray-400 text-xs">
                    {entry.created_at ? new Date(entry.created_at).toLocaleDateString() : '—'}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <button
                      onClick={() => handleRemove(entry.ticker)}
                      className="text-xs text-red-400 hover:text-red-600 font-medium"
                    >
                      Remove
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
