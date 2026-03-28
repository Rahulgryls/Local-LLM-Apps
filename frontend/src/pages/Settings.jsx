/**
 * LAKO — Settings Page
 * Configure model roles, Ollama URL, ChromaDB path,
 * Confluence credentials, RAG parameters.
 * All values read from / saved to config.json via backend.
 * Session 1: Shell — full implementation in Session 3.
 */

import React, { useState } from 'react'
import { Save } from 'lucide-react'

const DEFAULT_SETTINGS = {
  primary_model:        'qwen3.5:9b',
  vision_model:         'llava:13b',
  embedding_model:      'nomic-embed-text',
  ollama_url:           'http://localhost:11434',
  chromadb_path:        '/lako/storage/chromadb',
  confluence_url:       'https://yourbank.atlassian.net',
  confluence_email:     '',
  confluence_token:     '',
  top_k:                5,
  similarity_threshold: 0.7,
  api_key:              '',
}

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

export default function Settings() {
  const [settings, setSettings] = useState(DEFAULT_SETTINGS)
  const [saved, setSaved] = useState(false)

  const handleChange = (e) => {
    setSettings(prev => ({ ...prev, [e.target.name]: e.target.value }))
    setSaved(false)
  }

  const handleSave = async () => {
    // TODO (Session 3): POST settings to backend → write config.json
    console.log('[STUB] Save settings — Session 3', settings)
    setSaved(true)
    setTimeout(() => setSaved(false), 2000)
  }

  return (
    <div className="max-w-2xl space-y-6">
      <h2 className="text-lg font-semibold text-white">Settings</h2>

      {/* Model Settings */}
      <section>
        <h3 className="text-sm font-semibold text-gray-300 mb-3 border-b border-gray-800 pb-2">
          Model Configuration
        </h3>
        <div className="space-y-3">
          <Field label="Primary LLM"      name="primary_model"   value={settings.primary_model}   onChange={handleChange} />
          <Field label="Vision Model"     name="vision_model"    value={settings.vision_model}    onChange={handleChange} />
          <Field label="Embedding Model"  name="embedding_model" value={settings.embedding_model} onChange={handleChange} />
          <Field label="Ollama URL"       name="ollama_url"      value={settings.ollama_url}      onChange={handleChange} />
        </div>
      </section>

      {/* RAG Settings */}
      <section>
        <h3 className="text-sm font-semibold text-gray-300 mb-3 border-b border-gray-800 pb-2">
          RAG Configuration
        </h3>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Top-K Chunks"         name="top_k"                value={settings.top_k}                onChange={handleChange} type="number" />
          <Field label="Similarity Threshold" name="similarity_threshold" value={settings.similarity_threshold} onChange={handleChange} type="number" />
        </div>
        <div className="mt-3">
          <Field label="ChromaDB Path" name="chromadb_path" value={settings.chromadb_path} onChange={handleChange} />
        </div>
      </section>

      {/* Confluence Settings */}
      <section>
        <h3 className="text-sm font-semibold text-gray-300 mb-3 border-b border-gray-800 pb-2">
          Confluence
        </h3>
        <div className="space-y-3">
          <Field label="Confluence URL"   name="confluence_url"   value={settings.confluence_url}   onChange={handleChange} />
          <Field label="Email"            name="confluence_email" value={settings.confluence_email} onChange={handleChange} type="email" />
          <Field label="API Token"        name="confluence_token" value={settings.confluence_token} onChange={handleChange} type="password" placeholder="Paste token here" />
        </div>
      </section>

      {/* API Key */}
      <section>
        <h3 className="text-sm font-semibold text-gray-300 mb-3 border-b border-gray-800 pb-2">
          REST API Gateway
        </h3>
        <Field label="API Key (optional)" name="api_key" value={settings.api_key} onChange={handleChange} type="password" placeholder="Leave empty to disable auth" />
      </section>

      <button
        onClick={handleSave}
        className="flex items-center gap-2 px-5 py-2.5 bg-blue-600 rounded-xl text-sm text-white hover:bg-blue-500 transition-colors"
      >
        <Save size={14} />
        {saved ? 'Saved!' : 'Save Settings'}
      </button>

      <p className="text-xs text-gray-600">[STUB] Settings persistence wired in Session 3.</p>
    </div>
  )
}
