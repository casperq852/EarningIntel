import client from './client'

// ---------------------------------------------------------------------------
// Companies
// ---------------------------------------------------------------------------

export const getCompanies = () =>
  client.get('/companies').then((r) => r.data)

export const getCompany = (ticker) =>
  client.get(`/companies/${ticker}`).then((r) => r.data)

export const createCompany = (payload) =>
  client.post('/companies', payload).then((r) => r.data)

export const updateCompany = (ticker, payload) =>
  client.put(`/companies/${ticker}`, payload).then((r) => r.data)

// ---------------------------------------------------------------------------
// Earnings
// ---------------------------------------------------------------------------

export const getRecentEarnings = () =>
  client.get('/earnings/recent').then((r) => r.data)

export const getEarningsTrends = (tickers, quarters = 5) =>
  client.get('/earnings/trends', { params: { tickers: tickers.join(','), quarters } }).then((r) => r.data)

export const getEarnings = (ticker) =>
  client.get(`/earnings/${ticker}`).then((r) => r.data)

export const getSingleEarnings = (ticker, period) =>
  client.get(`/earnings/${ticker}/${period}`).then((r) => r.data)

// ---------------------------------------------------------------------------
// Calendar
// ---------------------------------------------------------------------------

export const getCalendar = (days = 14) =>
  client.get('/calendar', { params: { days } }).then((r) => r.data)

export const getTodaysEarnings = () =>
  client.get('/calendar/today').then((r) => r.data)

// ---------------------------------------------------------------------------
// Synthesis (pre/post briefs)
// ---------------------------------------------------------------------------

export const triggerPreBrief = (ticker) =>
  client.post(`/synthesise/pre/${ticker}`).then((r) => r.data)

export const triggerPostBrief = (ticker) =>
  client.post(`/synthesise/post/${ticker}`).then((r) => r.data)

// ---------------------------------------------------------------------------
// Documents
// ---------------------------------------------------------------------------

export const getDocuments = (ticker, period) =>
  client.get(`/documents/${ticker}/${period}`).then((r) => r.data)

export const getDocumentDownloadUrl = (docId) =>
  `${client.defaults.baseURL}/documents/${docId}/download`

// ---------------------------------------------------------------------------
// Synthesis (backfill / from-docs)
// ---------------------------------------------------------------------------

export const triggerBackfill = (ticker) =>
  client.post(`/synthesise/backfill/${ticker}`).then((r) => r.data)

// ---------------------------------------------------------------------------
// Onboarding
// ---------------------------------------------------------------------------

export const getOnboardStatus = (ticker) =>
  client.get(`/onboard/${ticker}/status`).then((r) => r.data)

export const triggerFromDocs = (ticker, period) =>
  client.post(`/synthesise/from-docs/${ticker}/${period}`).then((r) => r.data)

// ---------------------------------------------------------------------------
// Chat
// ---------------------------------------------------------------------------

export const getChatSuggestions = (ticker, period) =>
  client.get(`/chat/${ticker}/${period}/suggestions`).then((r) => r.data)

export const getBaseURL = () => client.defaults.baseURL

// ---------------------------------------------------------------------------
// Settings
// ---------------------------------------------------------------------------

export const getSettings = () =>
  client.get('/settings').then((r) => r.data)

export const updateSettings = (payload) =>
  client.put('/settings', payload).then((r) => r.data)

// ---------------------------------------------------------------------------
// Watchlist
// ---------------------------------------------------------------------------

export const getWatchlist = (email) =>
  client.get(`/watchlist/${encodeURIComponent(email)}`).then((r) => r.data)

export const addToWatchlist = (email, ticker) =>
  client.post(`/watchlist/${encodeURIComponent(email)}/${ticker}`).then((r) => r.data)

export const removeFromWatchlist = (email, ticker) =>
  client.delete(`/watchlist/${encodeURIComponent(email)}/${ticker}`).then((r) => r.data)

export const updateWatchlistPrefs = (email, ticker, prefs) =>
  client.patch(`/watchlist/${encodeURIComponent(email)}/${ticker}`, null, { params: prefs }).then((r) => r.data)

export const updateAlertConditions = (email, ticker, conditions) =>
  client.patch(`/watchlist/${encodeURIComponent(email)}/${ticker}`, null, {
    params: { alert_conditions: JSON.stringify(conditions) }
  }).then((r) => r.data)
