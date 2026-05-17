import { Routes, Route } from 'react-router-dom'
import NavBar from './components/NavBar'
import Dashboard from './pages/Dashboard'
import CompanyList from './pages/CompanyList'
import CompanyDetail from './pages/CompanyDetail'
import EarningsDetail from './pages/EarningsDetail'
import AddCompany from './pages/AddCompany'
import Watchlist from './pages/Watchlist'
import Settings from './pages/Settings'

export default function App() {
  return (
    <div className="min-h-screen bg-gray-50 font-sans">
      <NavBar />
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/companies" element={<CompanyList />} />
          <Route path="/companies/new" element={<AddCompany />} />
          <Route path="/companies/:ticker" element={<CompanyDetail />} />
          <Route path="/earnings/:ticker/:period" element={<EarningsDetail />} />
          <Route path="/watchlist" element={<Watchlist />} />
          <Route path="/settings" element={<Settings />} />
          <Route
            path="*"
            element={
              <div className="text-center py-20">
                <div className="text-6xl mb-4">404</div>
                <div className="text-gray-500">Page not found</div>
              </div>
            }
          />
        </Routes>
      </main>
    </div>
  )
}
