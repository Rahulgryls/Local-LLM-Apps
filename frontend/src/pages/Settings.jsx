/**
 * LAKO — Settings Page
 * Loads current config from GET /api/config.
 * Populates model dropdowns from GET /api/models (live Ollama list).
 * Saves via POST /api/config.
 * API Gateway section: full key management (generate, list, revoke, delete).
 * Session 3: Config wired. Session 10: API key management added.
 */

import React, { useState, useEffect, useCallback } from 'react'
import {
  Save, RefreshCw, Plus, Trash2, Ban, Copy, Check,
  Eye, EyeOff, Key, ChevronDown, ChevronUp,
} from 'lucide-react'

// ── Shared sub-components ────────────────────────────────────────────────────

function Field({ label, name, value, onChange, type = 'text', placeholder = '' }) {
  return (
    <div>
      <label className="block text-xs text-gray-500 mb-1">{label}</label>
      <input
        type={type}
        name={name}
        value={value}
        onChange={onChange}
        placeholder={placeholder}
        className="w-full bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-100 placeholder-gray-600 focus:outline-none focus:border-blue-600 transition-colors"
      />
    </div>
  )
}

function ModelSelect({ label, name, value, onChange, models }) {
  return (
    <div>
      <label className="block text-xs text-gray-500 mb-1">{label}</label>
      <select
        name={name}
        value={value}
        onChange={onChange}
        className="w-full bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-100 focus:outline-none focus:border-blue-600 transition-colors"
      >
        {!models.find(m => m.name === value) && (
          <option value={value}>{value} (not installed)</option>
        )}
        {models.map(m => (
          <option key={m.name} value={m.name}>
            {m.name}{m.size ? `  —  ${m.size}` : ''}
          </option>
        ))}
      </select>
    </div>
  )
}

// ── API Keys sub-components ──────────────────────────────────────────────────

function PermBadge({ label, active }) {
  return (
    <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${
      active ? 'bg-blue-900/60 text-blue-300' : 'bg-gray-800 text-gray-600'
    }`}>
      {label}
    </span>
  )
}

function CopyButton({ text }) {
  const [copied, setCopied] = useState(false)
  const copy = () => {
    navigator.clipboard.writeText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }
  return (
    <button onClick={copy} title="Copy to clipboard"
      className="p-1.5 rounded-lg bg-gray-700 hover:bg-gray-600 transition-colors">
      {copied ? <Check size={13} className="text-green-400" /> : <Copy size={13} className="text-gray-300" />}
    </button>
  )
}

function GenerateKeyModal({ onClose, onCreated }) {
  const [name, setName]         = useState('')
  const [perms, setPerms]       = useState({ query: true, ingest: false })
  const [loading, setLoading]   = useState(false)
  const [result, setResult]     = useState(null)   // {key, id, prefix}
  const [error, setError]       = useState('')
  const [showKey, setShowKey]   = useState(false)

  const togglePerm = (p) => setPerms(prev => ({ ...prev, [p]: !prev[p] }))

  const handleGenerate = async () => {
    if (!name.trim()) { setError('Name is required.'); return }
    const selectedPerms = Object.entries(perms).filter(([, v]) => v).map(([k]) => k)
    if (!selectedPerms.length) { setError('Select at least one permission.'); return }
    setLoading(true)
    setError('')
    try {
      const res = await fetch('/api/admin/keys', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ name: name.trim(), permissions: selectedPerms }),
      })
      const data = await res.json()
      if (!res.ok) { setError(data.detail || 'Failed to generate key.'); return }
      setResult(data)
      onCreated()
    } catch {
      setError('Cannot reach backend.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4">
      <div className="bg-gray-900 border border-gray-700 rounded-2xl w-full max-w-md p-6 space-y-4">
        {!result ? (
          <>
            <h3 className="text-sm font-semibold text-white">Generate New API Key</h3>

            <Field
              label="Consumer Name (e.g. CRM System, Data Pipeline)"
              name="name"
              value={name}
              onChange={e => setName(e.target.value)}
              placeholder="My Integration"
            />

            <div>
              <label className="block text-xs text-gray-500 mb-2">Permissions</label>
              <div className="flex gap-3">
                {['query', 'ingest'].map(p => (
                  <label key={p} className="flex items-center gap-2 cursor-pointer text-sm text-gray-300">
                    <input
                      type="checkbox"
                      checked={perms[p]}
                      onChange={() => togglePerm(p)}
                      className="rounded border-gray-600 bg-gray-800 text-blue-600 focus:ring-blue-600"
                    />
                    {p === 'query' ? 'Query (read)' : 'Ingest (write)'}
                  </label>
                ))}
              </div>
            </div>

            {error && <p className="text-xs text-red-400">{error}</p>}

            <div className="flex gap-2 pt-1">
              <button onClick={onClose}
                className="flex-1 py-2 bg-gray-800 rounded-xl text-sm text-gray-300 hover:bg-gray-700 transition-colors">
                Cancel
              </button>
              <button onClick={handleGenerate} disabled={loading}
                className="flex-1 py-2 bg-blue-600 rounded-xl text-sm text-white hover:bg-blue-500 disabled:opacity-50 transition-colors flex items-center justify-center gap-2">
                {loading ? <RefreshCw size={13} className="animate-spin" /> : <Key size={13} />}
                Generate
              </button>
            </div>
          </>
        ) : (
          <>
            <h3 className="text-sm font-semibold text-white">API Key Created</h3>
            <div className="rounded-xl bg-amber-950/40 border border-amber-700/50 px-4 py-3 text-xs text-amber-300 space-y-1">
              <p className="font-semibold">⚠️ Save this key now.</p>
              <p>It will never be shown again. If lost, delete it and generate a new one.</p>
            </div>

            <div>
              <label className="block text-xs text-gray-500 mb-1.5">API Key</label>
              <div className="flex items-center gap-2 bg-gray-800 border border-gray-700 rounded-lg px-3 py-2">
                <code className={`flex-1 text-xs text-green-400 break-all font-mono ${showKey ? '' : 'blur-sm select-none'}`}>
                  {result.key}
                </code>
                <button onClick={() => setShowKey(v => !v)} className="text-gray-500 hover:text-gray-300 flex-shrink-0">
                  {showKey ? <EyeOff size={13} /> : <Eye size={13} />}
                </button>
                <CopyButton text={result.key} />
              </div>
            </div>

            <div className="text-xs text-gray-500 space-y-0.5">
              <p><span className="text-gray-600">ID:</span> {result.id}</p>
              <p><span className="text-gray-600">Prefix:</span> {result.prefix}…</p>
            </div>

            <button onClick={onClose}
              className="w-full py-2.5 bg-blue-600 rounded-xl text-sm text-white hover:bg-blue-500 transition-colors">
              Done
            </button>
          </>
        )}
      </div>
    </div>
  )
}

function KeysTable({ keys, onRevoke, onDelete }) {
  if (!keys.length) {
    return (
      <p className="text-xs text-gray-600 py-3">
        No API keys yet. Generate one to enable gateway access.
      </p>
    )
  }

  const fmt = (iso) => iso ? new Date(iso).toLocaleDateString('en-GB', { day:'2-digit', month:'short', year:'2-digit' }) : '—'

  return (
    <div className="rounded-xl border border-gray-800 overflow-hidden">
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-gray-800 bg-gray-900/60">
            {['Name', 'Prefix', 'Permissions', 'Created', 'Last Used', 'Status', ''].map(h => (
              <th key={h} className="text-left px-3 py-2 text-gray-500 font-medium">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {keys.map(k => (
            <tr key={k.id} className="border-b border-gray-800/50 last:border-0 hover:bg-gray-800/30">
              <td className="px-3 py-2.5 text-gray-300 font-medium">{k.name}</td>
              <td className="px-3 py-2.5 font-mono text-gray-400">{k.prefix}…</td>
              <td className="px-3 py-2.5">
                <div className="flex gap-1">
                  <PermBadge label="query"  active={k.permissions.includes('query')}  />
                  <PermBadge label="ingest" active={k.permissions.includes('ingest')} />
                </div>
              </td>
              <td className="px-3 py-2.5 text-gray-500">{fmt(k.created_at)}</td>
              <td className="px-3 py-2.5 text-gray-500">{fmt(k.last_used)}</td>
              <td className="px-3 py-2.5">
                <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${
                  k.is_active ? 'bg-green-900/50 text-green-400' : 'bg-gray-800 text-gray-500'
                }`}>
                  {k.is_active ? 'Active' : 'Revoked'}
                </span>
              </td>
              <td className="px-3 py-2.5">
                <div className="flex gap-1.5 justify-end">
                  {k.is_active && (
                    <button onClick={() => onRevoke(k.id)} title="Revoke key"
                      className="p-1 rounded hover:bg-gray-700 text-yellow-500 hover:text-yellow-400 transition-colors">
                      <Ban size={13} />
                    </button>
                  )}
                  <button onClick={() => onDelete(k.id)} title="Delete key"
                    className="p-1 rounded hover:bg-gray-700 text-red-500 hover:text-red-400 transition-colors">
                    <Trash2 size={13} />
                  </button>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ── Main component ───────────────────────────────────────────────────────────

const EMPTY_SETTINGS = {
  primary_model:        '',
  vision_model:         '',
  embedding_model:      '',
  ollama_url:           'http://localhost:11434',
  chromadb_path:        '',
  confluence_url:       '',
  confluence_email:     '',
  confluence_token:     '',
  top_k:                5,
  similarity_threshold: 0.7,
  api_key:              '',
}

export default function Settings() {
  const [settings, setSettings]   = useState(EMPTY_SETTINGS)
  const [models, setModels]       = useState([])
  const [loading, setLoading]     = useState(true)
  const [saveState, setSaveState] = useState('idle')   // idle | saving | saved | error
  const [errorMsg, setErrorMsg]   = useState('')

  // API keys state
  const [apiKeys, setApiKeys]           = useState([])
  const [keysLoading, setKeysLoading]   = useState(false)
  const [showModal, setShowModal]       = useState(false)
  const [keysExpanded, setKeysExpanded] = useState(true)

  useEffect(() => { loadAll() }, [])

  async function loadAll() {
    setLoading(true)
    try {
      const [configRes, modelsRes] = await Promise.all([
        fetch('/api/config'),
        fetch('/api/models'),
      ])
      const config = await configRes.json()
      const modelsData = await modelsRes.json()
      setSettings(prev => ({ ...prev, ...config }))
      setModels(modelsData.models || [])
    } catch {
      setErrorMsg('Could not load settings from backend.')
    } finally {
      setLoading(false)
    }
    loadKeys()
  }

  const loadKeys = useCallback(async () => {
    setKeysLoading(true)
    try {
      const res = await fetch('/api/admin/keys')
      if (res.ok) setApiKeys(await res.json())
    } catch { /* ignore */ }
    finally { setKeysLoading(false) }
  }, [])

  const handleChange = (e) => {
    const { name, value } = e.target
    setSettings(prev => ({ ...prev, [name]: value }))
    setSaveState('idle')
  }

  const handleSave = async () => {
    setSaveState('saving')
    setErrorMsg('')
    try {
      const res = await fetch('/api/config', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({
          ...settings,
          top_k:                Number(settings.top_k),
          similarity_threshold: Number(settings.similarity_threshold),
        }),
      })
      if (!res.ok) {
        const err = await res.json()
        throw new Error(err.detail || 'Save failed')
      }
      setSaveState('saved')
      setTimeout(() => setSaveState('idle'), 2500)
    } catch (err) {
      setSaveState('error')
      setErrorMsg(err.message)
    }
  }

  const handleRevoke = async (id) => {
    if (!confirm('Revoke this API key? It will stop working immediately.')) return
    await fetch(`/api/admin/keys/${id}/revoke`, { method: 'PATCH' })
    loadKeys()
  }

  const handleDelete = async (id) => {
    if (!confirm('Permanently delete this API key?')) return
    await fetch(`/api/admin/keys/${id}`, { method: 'DELETE' })
    loadKeys()
  }

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-gray-500 text-sm">
        <RefreshCw size={14} className="animate-spin" />
        Loading settings...
      </div>
    )
  }

  return (
    <div className="max-w-2xl space-y-6">
      <h2 className="text-lg font-semibold text-white">Settings</h2>

      {/* Model Configuration */}
      <section>
        <h3 className="text-sm font-semibold text-gray-300 mb-3 border-b border-gray-800 pb-2">
          Model Configuration
        </h3>
        <div className="space-y-3">
          <ModelSelect label="Primary LLM"      name="primary_model"   value={settings.primary_model}   onChange={handleChange} models={models} />
          <ModelSelect label="Vision Model"     name="vision_model"    value={settings.vision_model}    onChange={handleChange} models={models} />
          <ModelSelect label="Embedding Model"  name="embedding_model" value={settings.embedding_model} onChange={handleChange} models={models} />
          <Field       label="Ollama URL"       name="ollama_url"      value={settings.ollama_url}      onChange={handleChange} />
        </div>
      </section>

      {/* RAG Configuration */}
      <section>
        <h3 className="text-sm font-semibold text-gray-300 mb-3 border-b border-gray-800 pb-2">
          RAG Configuration
        </h3>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Top-K Chunks"        name="top_k"                value={settings.top_k}                onChange={handleChange} type="number" />
          <Field label="Similarity Threshold" name="similarity_threshold" value={settings.similarity_threshold} onChange={handleChange} type="number" />
        </div>
        <div className="mt-3">
          <Field label="ChromaDB Path" name="chromadb_path" value={settings.chromadb_path} onChange={handleChange} />
        </div>
      </section>

      {/* Confluence */}
      <section>
        <h3 className="text-sm font-semibold text-gray-300 mb-3 border-b border-gray-800 pb-2">
          Confluence
        </h3>
        <div className="space-y-3">
          <Field label="Confluence URL" name="confluence_url"   value={settings.confluence_url}   onChange={handleChange} />
          <Field label="Email"          name="confluence_email" value={settings.confluence_email} onChange={handleChange} type="email" />
          <Field label="API Token"      name="confluence_token" value={settings.confluence_token} onChange={handleChange} type="password" placeholder="Paste token here" />
        </div>
      </section>

      {/* Error + Save */}
      {saveState === 'error' && <p className="text-xs text-red-400">{errorMsg}</p>}
      <button
        onClick={handleSave}
        disabled={saveState === 'saving'}
        className="flex items-center gap-2 px-5 py-2.5 bg-blue-600 rounded-xl text-sm text-white hover:bg-blue-500 disabled:opacity-50 transition-colors"
      >
        <Save size={14} />
        {saveState === 'saving' ? 'Saving...' : saveState === 'saved' ? 'Saved!' : 'Save Settings'}
      </button>

      {/* API Gateway */}
      <section>
        <button
          onClick={() => setKeysExpanded(v => !v)}
          className="w-full flex items-center justify-between text-sm font-semibold text-gray-300 border-b border-gray-800 pb-2 hover:text-white transition-colors"
        >
          <span className="flex items-center gap-2">
            <Key size={14} />
            REST API Gateway — API Keys
          </span>
          {keysExpanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
        </button>

        {keysExpanded && (
          <div className="mt-4 space-y-4">
            <p className="text-xs text-gray-500">
              API keys allow internal systems to query the knowledge base via{' '}
              <code className="text-gray-400">POST /api/gateway/query</code>.
              All requests must include{' '}
              <code className="text-gray-400">X-API-Key: lako_…</code> in the header.
            </p>

            <div className="flex items-center justify-between">
              <span className="text-xs text-gray-500">
                {apiKeys.length} key{apiKeys.length !== 1 ? 's' : ''} ·{' '}
                {apiKeys.filter(k => k.is_active).length} active
              </span>
              <div className="flex gap-2">
                <button onClick={loadKeys} title="Refresh"
                  className="p-1.5 rounded-lg bg-gray-800 hover:bg-gray-700 text-gray-400 transition-colors">
                  <RefreshCw size={13} className={keysLoading ? 'animate-spin' : ''} />
                </button>
                <button onClick={() => setShowModal(true)}
                  className="flex items-center gap-1.5 px-3 py-1.5 bg-blue-600 rounded-lg text-xs text-white hover:bg-blue-500 transition-colors">
                  <Plus size={12} />
                  Generate Key
                </button>
              </div>
            </div>

            <KeysTable keys={apiKeys} onRevoke={handleRevoke} onDelete={handleDelete} />

            <div className="rounded-lg bg-gray-900 border border-gray-800 px-3 py-2 text-xs text-gray-600 space-y-0.5">
              <p className="font-medium text-gray-500">Example usage</p>
              <code className="text-gray-500 block">
                curl -X POST http://localhost:8000/api/gateway/query \
              </code>
              <code className="text-gray-500 block pl-4">
                -H "X-API-Key: lako_…" \
              </code>
              <code className="text-gray-500 block pl-4">
                -d '{`{"question":"What is the KYC policy?"}`}'
              </code>
            </div>
          </div>
        )}
      </section>

      {showModal && (
        <GenerateKeyModal
          onClose={() => setShowModal(false)}
          onCreated={loadKeys}
        />
      )}
    </div>
  )
}
