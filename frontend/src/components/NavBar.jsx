import { NavLink } from 'react-router-dom'

const NAV_LINKS = [
  { to: '/', label: 'Dashboard', exact: true },
  { to: '/companies', label: 'Companies' },
  { to: '/watchlist', label: 'Watchlist' },
]

export default function NavBar() {
  return (
    <nav className="bg-white border-b border-gray-100 sticky top-0 z-10 shadow-sm">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center h-14 gap-8">
          {/* Logo */}
          <div className="flex items-center gap-2 flex-shrink-0">
            <div className="w-7 h-7 rounded-lg bg-blue-600 flex items-center justify-center">
              <svg className="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />
              </svg>
            </div>
            <span className="font-bold text-gray-900 text-sm tracking-tight">EarningIntel</span>
          </div>

          {/* Nav links */}
          <div className="flex items-center gap-1">
            {NAV_LINKS.map(({ to, label, exact }) => (
              <NavLink
                key={to}
                to={to}
                end={exact}
                className={({ isActive }) =>
                  `px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                    isActive
                      ? 'bg-blue-50 text-blue-700'
                      : 'text-gray-600 hover:text-gray-900 hover:bg-gray-50'
                  }`
                }
              >
                {label}
              </NavLink>
            ))}
          </div>

          {/* Right side — version badge */}
          <div className="ml-auto">
            <span className="text-xs text-gray-400 font-mono">v1.0</span>
          </div>
        </div>
      </div>
    </nav>
  )
}
