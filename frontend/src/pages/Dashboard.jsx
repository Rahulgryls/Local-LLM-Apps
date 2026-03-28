/**
 * LAKO — Dashboard Page
 * Model health status cards — live from GET /api/models.
 * Green = model installed in Ollama. Red = not found.
 * ChromaDB stats stub — wired in Session 4.
 * Session 3: Model health cards fully wired.
 */

import React, { useState, useEffect } from 'react'
import { RefreshCw, CheckCircle, XCircle, Database, WifiOff } from 'lucide-react'

const MODEL_ROLES = [
  { role: 'Primary LLM',     key: 'primary_model' },
  { role: 'Vision Model',    key: 'vision_model' },
  { role: 'Embedding Model', key: 'embedding_model' },
]

export default function Dashboard() {
  const [modelsData, setModelsData] = useState(null)
  const [loading, setLoading]       = useState(false)
  const [vectorStats]               = useState({ status: 'stub', total_chunks: 0 })

  const fetchModels = async () => {
    setLoading(true)
    try {
      const res = await fetch('/api/models')
      const data = await res.json()
      setModelsData(data)
    } catch (err) {
      console.error('[Dashboard] Failed to fetch models:', err)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchModels()
  }, [])

  return (
    <div className="max-w-4xl space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-white">System Dashboard</h2>
        <button
          onClick={fetchModels}
          disabled={loading}
          className="flex items-center gap-2 text-xs px-3 py-2 rounded bg-gray-800 text-gray-400 hover:text-white disabled:opacity-50 transition-colors"
        >
          <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
          Refresh Models
        </button>
      </div>

      {/* Ollama unreachable banner */}
      {modelsData && !modelsData.ollama_reachable && (
        <div className="flex items-center gap-2 text-xs text-yellow-400 bg-yellow-400/10 border border-yellow-400/20 rounded-lg px-4 py-3">
          <WifiOff size={13} />
          Ollama is not reachable at {modelsData.ollama_url || 'localhost:11434'}.
          Start Ollama and click Refresh Models.
        </div>
      )}

      {/* Model Health Cards */}
      <div className="grid grid-cols-3 gap-4">
        {MODEL_ROLES.map(({ role, key }) => {
          const modelName = modelsData?.[key]
          const healthy   = modelsData?.model_health?.[key]

          return (
            <div key={key} className="bg-gray-900 border border-gray-800 rounded-xl p-4">
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs text-gray-500">{role}</span>
                {loading || !modelsData ? (
                  <div className="w-3.5 h-3.5 rounded-full bg-gray-700 animate-pulse" />
                ) : healthy === true ? (
                  <CheckCircle size={14} className="text-green-400" />
                ) : (
                  <XCircle size={14} className="text-red-400" />
                )}
              </div>
              <p className="text-sm font-mono text-blue-400 truncate">
                {modelName || '…'}
              </p>
            </div>
          )
        })}
      </div>

      {/* Vector DB Stats */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
        <div className="flex items-center gap-2 mb-4">
          <Database size={16} className="text-blue-400" />
          <h3 className="text-sm font-semibold text-white">Vector Database</h3>
        </div>
        <div className="grid grid-cols-3 gap-4 text-sm">
          <div>
            <p className="text-gray-500 text-xs">Status</p>
            <p className="text-white mt-1">{vectorStats.status}</p>
          </div>
          <div>
            <p className="text-gray-500 text-xs">Total Chunks</p>
            <p className="text-white mt-1">{vectorStats.total_chunks}</p>
          </div>
          <div>
            <p className="text-gray-500 text-xs">Storage</p>
            <p className="text-white mt-1">ChromaDB (local)</p>
          </div>
        </div>
      </div>

      <p className="text-xs text-gray-600">
        Vector DB stats wired in Session 4.
      </p>
    </div>
  )
}
