import { useEffect, useState } from 'react'
import client from '../api/client'

// Pricing verified against OpenRouter API, May 2026. input/output = $ per 1M tokens.
const ANTHROPIC_MODELS = [
  { id: 'claude-sonnet-4-20250514', name: 'Claude Sonnet 4.6', note: 'Default', input: 3.00,  output: 15.00, ctx: '200K' },
  { id: 'claude-opus-4-7-20251101', name: 'Claude Opus 4.7',   note: 'Best',    input: 15.00, output: 75.00, ctx: '200K' },
  { id: 'claude-haiku-4-5-20251001',name: 'Claude Haiku 4.5',  note: 'Fast',    input: 0.80,  output: 4.00,  ctx: '200K' },
]

const OPENROUTER_MODELS = [
  // --- Premium ---
  { id: 'anthropic/claude-opus-latest',  name: 'Claude Opus',        note: 'Premium',     input: 5.00,    output: 25.00,  ctx: '1M',   tier: 'premium' },
  { id: 'anthropic/claude-sonnet-latest',name: 'Claude Sonnet',      note: 'Recommended', input: 3.00,    output: 15.00,  ctx: '1M',   tier: 'premium' },
  { id: 'openai/gpt-5.5',               name: 'GPT-5.5',            note: null,           input: 5.00,    output: 30.00,  ctx: '1M',   tier: 'premium' },
  { id: 'openai/gpt-5.4',              name: 'GPT-5.4',             note: null,           input: 2.50,    output: 15.00,  ctx: '1M',   tier: 'premium' },
  // --- Mid ---
  { id: 'anthropic/claude-haiku-latest', name: 'Claude Haiku',       note: null,           input: 1.00,    output: 5.00,   ctx: '200K', tier: 'mid' },
  { id: 'mistralai/mistral-medium-3.5',  name: 'Mistral Medium 3.5', note: null,           input: 1.50,    output: 7.50,   ctx: '262K', tier: 'mid' },
  { id: 'x-ai/grok-4.3',               name: 'Grok 4.3',           note: null,           input: 1.25,    output: 2.50,   ctx: '1M',   tier: 'mid' },
  { id: 'openai/gpt-5.4-mini',          name: 'GPT-5.4 Mini',       note: null,           input: 0.75,    output: 4.50,   ctx: '400K', tier: 'mid' },
  { id: 'google/gemini-flash-latest',   name: 'Gemini Flash',       note: null,           input: 0.50,    output: 3.00,   ctx: '1M',   tier: 'mid' },
  // --- Budget ---
  { id: 'deepseek/deepseek-v4-pro',     name: 'DeepSeek V4 Pro',    note: 'Best value',   input: 0.44,    output: 0.87,   ctx: '1M',   tier: 'budget' },
  { id: 'mistralai/mistral-small-2603', name: 'Mistral Small 4',    note: null,           input: 0.15,    output: 0.60,   ctx: '262K', tier: 'budget' },
  { id: 'openai/gpt-5.4-nano',          name: 'GPT-5.4 Nano',       note: null,           input: 0.20,    output: 1.25,   ctx: '400K', tier: 'budget' },
  { id: 'google/gemini-3.1-flash-lite', name: 'Gemini 3.1 Flash Lite', note: null,        input: 0.25,    output: 1.50,   ctx: '1M',   tier: 'budget' },
  { id: 'deepseek/deepseek-v4-flash',   name: 'DeepSeek V4 Flash',  note: null,           input: 0.11,    output: 0.22,   ctx: '1M',   tier: 'budget' },
  // --- Free ---
  { id: 'deepseek/deepseek-v4-flash:free', name: 'DeepSeek V4 Flash', note: 'Free tier',  input: 0,       output: 0,      ctx: '1M',   tier: 'free' },
  { id: 'google/gemma-4-31b-it:free',   name: 'Gemma 4 31B',        note: 'Free tier',   input: 0,       output: 0,      ctx: '262K', tier: 'free' },
]

const TIER_LABEL = { premium: 'Premium', mid: 'Mid', budget: 'Budget', free: 'Free' }
const TIER_COLOR = {
  premium: 'text-purple-600 bg-purple-50',
  mid:     'text-blue-600 bg-blue-50',
  budget:  'text-emerald-600 bg-emerald-50',
  free:    'text-gray-500 bg-gray-100',
}

function fmtPrice(n) {
  if (n === 0) return <span className="text-emerald-600 font-semibold">Free</span>
  if (n < 0.10) return `$${n.toFixed(3)}`
  if (n < 1)    return `$${n.toFixed(2)}`
  return `$${n.toFixed(2)}`
}

function ModelTable({ models, selected, onSelect }) {
  const groups = ['premium', 'mid', 'budget', 'free']
  return (
    <div className="border border-gray-100 rounded-lg overflow-hidden text-xs">
      {/* Header */}
      <div className="grid grid-cols-[1fr_auto_auto_auto] bg-gray-50 border-b border-gray-100 px-3 py-1.5 text-gray-400 font-medium gap-x-4">
        <span>Model</span>
        <span className="text-right">Context</span>
        <span className="text-right">Input /M</span>
        <span className="text-right">Output /M</span>
      </div>
      {groups.map((tier) => {
        const rows = models.filter((m) => m.tier === tier)
        if (!rows.length) return null
        return (
          <div key={tier}>
            <div className={`px-3 py-1 text-[10px] font-semibold uppercase tracking-wide border-b border-gray-50 ${TIER_COLOR[tier]}`}>
              {TIER_LABEL[tier]}
            </div>
            {rows.map((m) => (
              <button
                key={m.id}
                onClick={() => onSelect(m.id)}
                className={`w-full grid grid-cols-[1fr_auto_auto_auto] items-center px-3 py-2 gap-x-4 border-b border-gray-50 last:border-0 text-left transition-colors ${
                  selected === m.id
                    ? 'bg-indigo-50'
                    : 'hover:bg-gray-50'
                }`}
              >
                <span className="flex items-center gap-1.5 min-w-0">
                  {selected === m.id && (
                    <span className="w-1.5 h-1.5 rounded-full bg-indigo-500 shrink-0" />
                  )}
                  {selected !== m.id && <span className="w-1.5 h-1.5 shrink-0" />}
                  <span className={`font-medium truncate ${selected === m.id ? 'text-indigo-700' : 'text-gray-700'}`}>
                    {m.name}
                  </span>
                  {m.note && (
                    <span className="shrink-0 text-[10px] px-1.5 py-0.5 rounded-full bg-amber-100 text-amber-700 font-medium">
                      {m.note}
                    </span>
                  )}
                </span>
                <span className="text-right text-gray-400 font-mono">{m.ctx}</span>
                <span className={`text-right font-mono ${selected === m.id ? 'text-indigo-600' : 'text-gray-600'}`}>
                  {fmtPrice(m.input)}
                </span>
                <span className={`text-right font-mono ${selected === m.id ? 'text-indigo-600' : 'text-gray-600'}`}>
                  {fmtPrice(m.output)}
                </span>
              </button>
            ))}
          </div>
        )
      })}
    </div>
  )
}

function AnthropicModelTable({ models, selected, onSelect }) {
  return (
    <div className="border border-gray-100 rounded-lg overflow-hidden text-xs">
      <div className="grid grid-cols-[1fr_auto_auto_auto] bg-gray-50 border-b border-gray-100 px-3 py-1.5 text-gray-400 font-medium gap-x-4">
        <span>Model</span>
        <span className="text-right">Context</span>
        <span className="text-right">Input /M</span>
        <span className="text-right">Output /M</span>
      </div>
      {models.map((m) => (
        <button
          key={m.id}
          onClick={() => onSelect(m.id)}
          className={`w-full grid grid-cols-[1fr_auto_auto_auto] items-center px-3 py-2 gap-x-4 border-b border-gray-50 last:border-0 text-left transition-colors ${
            selected === m.id ? 'bg-indigo-50' : 'hover:bg-gray-50'
          }`}
        >
          <span className="flex items-center gap-1.5 min-w-0">
            {selected === m.id
              ? <span className="w-1.5 h-1.5 rounded-full bg-indigo-500 shrink-0" />
              : <span className="w-1.5 h-1.5 shrink-0" />
            }
            <span className={`font-medium truncate ${selected === m.id ? 'text-indigo-700' : 'text-gray-700'}`}>
              {m.name}
            </span>
            {m.note && (
              <span className="shrink-0 text-[10px] px-1.5 py-0.5 rounded-full bg-amber-100 text-amber-700 font-medium">
                {m.note}
              </span>
            )}
          </span>
          <span className="text-right text-gray-400 font-mono">{m.ctx}</span>
          <span className={`text-right font-mono ${selected === m.id ? 'text-indigo-600' : 'text-gray-600'}`}>
            {fmtPrice(m.input)}
          </span>
          <span className={`text-right font-mono ${selected === m.id ? 'text-indigo-600' : 'text-gray-600'}`}>
            {fmtPrice(m.output)}
          </span>
        </button>
      ))}
    </div>
  )
}

function ModelSelector({ label, description, providerKey, modelKey, settings, onChange }) {
  const provider = settings[providerKey] || 'anthropic'
  const model = settings[modelKey] || ''
  const isOpenRouter = provider === 'openrouter'

  const orIds = OPENROUTER_MODELS.map((m) => m.id)
  const anIds = ANTHROPIC_MODELS.map((m) => m.id)
  const knownIds = isOpenRouter ? orIds : anIds
  const isCustom = model && !knownIds.includes(model)

  return (
    <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-5">
      <div className="mb-4">
        <h3 className="text-sm font-semibold text-gray-800">{label}</h3>
        <p className="text-xs text-gray-400 mt-0.5">{description}</p>
      </div>

      <div className="space-y-4">
        {/* Provider toggle */}
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1.5">Provider</label>
          <div className="flex gap-2">
            {['anthropic', 'openrouter'].map((p) => (
              <button
                key={p}
                onClick={() => {
                  const list = p === 'openrouter' ? OPENROUTER_MODELS : ANTHROPIC_MODELS
                  onChange({ [providerKey]: p, [modelKey]: list[0].id })
                }}
                className={`px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors ${
                  provider === p
                    ? 'bg-indigo-50 border-indigo-200 text-indigo-700'
                    : 'bg-white border-gray-200 text-gray-600 hover:border-gray-300'
                }`}
              >
                {p === 'anthropic' ? 'Anthropic' : 'OpenRouter'}
              </button>
            ))}
          </div>
        </div>

        {/* Model table */}
        {isOpenRouter ? (
          <ModelTable
            models={OPENROUTER_MODELS}
            selected={model}
            onSelect={(id) => onChange({ [modelKey]: id })}
          />
        ) : (
          <AnthropicModelTable
            models={ANTHROPIC_MODELS}
            selected={model}
            onSelect={(id) => onChange({ [modelKey]: id })}
          />
        )}

        {/* Custom model ID */}
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1.5">
            Custom model ID <span className="text-gray-400 font-normal">(type to override table)</span>
          </label>
          <input
            type="text"
            value={isCustom ? model : ''}
            onChange={(e) => {
              const val = e.target.value.trim()
              if (val) {
                onChange({ [modelKey]: val })
              } else {
                const list = isOpenRouter ? OPENROUTER_MODELS : ANTHROPIC_MODELS
                onChange({ [modelKey]: list[0].id })
              }
            }}
            placeholder={isOpenRouter ? 'e.g. cohere/command-r-plus' : 'e.g. claude-sonnet-4-20250514'}
            className="w-full text-xs border border-gray-200 rounded-lg px-3 py-2 text-gray-700 placeholder-gray-300 focus:outline-none focus:ring-1 focus:ring-indigo-300"
          />
        </div>
      </div>
    </div>
  )
}

export default function Settings() {
  const [settings, setSettings] = useState(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    client.get('/settings').then((r) => {
      setSettings(r.data)
      setLoading(false)
    }).catch(() => {
      setError('Could not load settings.')
      setLoading(false)
    })
  }, [])

  const handleChange = (patch) => {
    setSettings((s) => ({ ...s, ...patch }))
    setSaved(false)
  }

  const handleSave = async () => {
    setSaving(true)
    setError('')
    try {
      const r = await client.put('/settings', settings)
      setSettings(r.data)
      setSaved(true)
      setTimeout(() => setSaved(false), 3000)
    } catch (e) {
      setError('Failed to save settings.')
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-24">
        <div className="w-6 h-6 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin" />
      </div>
    )
  }

  return (
    <div className="max-w-2xl mx-auto space-y-6">
      <div>
        <h1 className="text-xl font-bold text-gray-900">Settings</h1>
        <p className="text-sm text-gray-400 mt-1">Configure which LLM is used for each step. Pricing is per 1M tokens.</p>
      </div>

      {/* Research step note */}
      <div className="bg-amber-50 border border-amber-100 rounded-xl p-4 flex gap-3">
        <svg className="w-4 h-4 text-amber-500 mt-0.5 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
        <div>
          <div className="text-xs font-semibold text-amber-700">Step 1 — Research is Anthropic-only</div>
          <div className="text-xs text-amber-600 mt-0.5">
            The research agent uses Anthropic's tool-calling API (web search, page scraping). It cannot be switched to OpenRouter.
          </div>
        </div>
      </div>

      <ModelSelector
        label="Step 2 — Bloomberg Parser"
        description="Extracts revenue, EBIT, EPS and segment data from the uploaded .xlsx file."
        providerKey="parser_provider"
        modelKey="parser_model"
        settings={settings}
        onChange={handleChange}
      />

      <ModelSelector
        label="Step 3 — Brief Synthesis"
        description="Writes pre-earnings and post-earnings briefs, and extracts from IR documents."
        providerKey="synthesis_provider"
        modelKey="synthesis_model"
        settings={settings}
        onChange={handleChange}
      />

      {/* OpenRouter API key */}
      <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-5">
        <div className="mb-3">
          <h3 className="text-sm font-semibold text-gray-800">OpenRouter API Key</h3>
          <p className="text-xs text-gray-400 mt-0.5">Required when either step above is set to OpenRouter.</p>
        </div>
        <input
          type="password"
          value={settings.openrouter_api_key || ''}
          onChange={(e) => handleChange({ openrouter_api_key: e.target.value || null })}
          placeholder="sk-or-..."
          className="w-full text-xs border border-gray-200 rounded-lg px-3 py-2 text-gray-700 placeholder-gray-300 focus:outline-none focus:ring-1 focus:ring-indigo-300"
        />
      </div>

      {error && <p className="text-xs text-red-600">{error}</p>}
      <div className="flex items-center gap-3">
        <button
          onClick={handleSave}
          disabled={saving}
          className="px-5 py-2 rounded-lg bg-indigo-600 text-white text-sm font-semibold hover:bg-indigo-700 disabled:opacity-50 transition-colors"
        >
          {saving ? 'Saving…' : 'Save Settings'}
        </button>
        {saved && <span className="text-xs text-emerald-600 font-medium">Saved</span>}
      </div>
    </div>
  )
}
