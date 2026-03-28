/**
 * LAKO — Settings Page
 * Loads current config from GET /api/config.
 * Populates model dropdowns from GET /api/models (live Ollama list).
 * Saves via POST /api/config.
 * Session 3: Fully wired.
 */

import React, { useState, useEffect } from 'react'
import { Save, RefreshCw } from 'lucide-react'

// Plain text input field
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

// Dropdown populated from Ollama model list
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
        {/* Keep current value selectable even if Ollama is offline */}
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
  const [models, setModels]       = useState([])          // live Ollama model list
  const [loading, setLoading]     = useState(true)
  const [saveState, setSaveState] = useState('idle')      // idle | saving | saved | error
  const [errorMsg, setErrorMsg]   = useState('')

  // Load config + model list on mount
  useEffect(() => {
    loadAll()
  }, [])

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
    } catch (err) {
      setErrorMsg('Could not load settings from backend.')
    } finally {
      setLoading(false)
    }
  }

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
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ...settings,
          top_k: Number(settings.top_k),
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
          <ModelSelect
            label="Primary LLM"
            name="primary_model"
            value={settings.primary_model}
            onChange={handleChange}
            models={models}
          />
          <ModelSelect
            label="Vision Model"
            name="vision_model"
            value={settings.vision_model}
            onChange={handleChange}
            models={models}
          />
          <ModelSelect
            label="Embedding Model"
            name="embedding_model"
            value={settings.embedding_model}
            onChange={handleChange}
            models={models}
          />
          <Field
            label="Ollama URL"
            name="ollama_url"
            value={settings.ollama_url}
            onChange={handleChange}
          />
        </div>
      </section>

      {/* RAG Configuration */}
      <section>
        <h3 className="text-sm font-semibold text-gray-300 mb-3 border-b border-gray-800 pb-2">
          RAG Configuration
        </h3>
        <div className="grid grid-cols-2 gap-3">
          <Field
            label="Top-K Chunks"
            name="top_k"
            value={settings.top_k}
            onChange={handleChange}
            type="number"
          />
          <Field
            label="Similarity Threshold"
            name="similarity_threshold"
            value={settings.similarity_threshold}
            onChange={handleChange}
            type="number"
          />
        </div>
        <div className="mt-3">
          <Field
            label="ChromaDB Path"
            name="chromadb_path"
            value={settings.chromadb_path}
            onChange={handleChange}
          />
        </div>
      </section>

      {/* Confluence */}
      <section>
        <h3 className="text-sm font-semibold text-gray-300 mb-3 border-b border-gray-800 pb-2">
          Confluence
        </h3>
        <div className="space-y-3">
          <Field
            label="Confluence URL"
            name="confluence_url"
            value={settings.confluence_url}
            onChange={handleChange}
          />
          <Field
            label="Email"
            name="confluence_email"
            value={settings.confluence_email}
            onChange={handleChange}
            type="email"
          />
          <Field
            label="API Token"
            name="confluence_token"
            value={settings.confluence_token}
            onChange={handleChange}
            type="password"
            placeholder="Paste token here"
          />
        </div>
      </section>

      {/* REST API Gateway */}
      <section>
        <h3 className="text-sm font-semibold text-gray-300 mb-3 border-b border-gray-800 pb-2">
          REST API Gateway
        </h3>
        <Field
          label="API Key (optional)"
          name="api_key"
          value={settings.api_key}
          onChange={handleChange}
          type="password"
          placeholder="Leave empty to disable auth"
        />
      </section>

      {/* Error message */}
      {saveState === 'error' && (
        <p className="text-xs text-red-400">{errorMsg}</p>
      )}

      {/* Save button */}
      <button
        onClick={handleSave}
        disabled={saveState === 'saving'}
        className="flex items-center gap-2 px-5 py-2.5 bg-blue-600 rounded-xl text-sm text-white hover:bg-blue-500 disabled:opacity-50 transition-colors"
      >
        <Save size={14} />
        {saveState === 'saving' ? 'Saving...' : saveState === 'saved' ? 'Saved!' : 'Save Settings'}
      </button>
    </div>
  )
}
