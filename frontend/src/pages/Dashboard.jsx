/**
 * LAKO — Dashboard Page
 * Model health status (green/red ping per role).
 * ChromaDB stats, ingestion status, Refresh Models button.
 * Session 1: Shell — full implementation in Session 11.
 */

import React, { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { RefreshCw, CheckCircle, XCircle, Database } from 'lucide-react'

const MODEL_ROLES = [
  { role: 'Primary LLM',      key: 'primary_model',    default: 'qwen3.5:9b' },
  { role: 'Vision Model',     key: 'vision_model',     default: 'llava:13b' },
  { role: 'Embedding Model',  key: 'embedding_model',  default: 'nomic-embed-text' },
]

export default function Dashboard() {
  const { t } = useTranslation()
  const [modelHealth] = useState({}) // TODO (Session 11): poll /api/models
  const [vectorStats] = useState({ status: 'stub', total_chunks: 0 }) // TODO (Session 11): poll /api/vector/status

  const handleRefreshModels = () => {
    // TODO (Session 11): call GET /api/models and update store
    console.log('[STUB] Refresh Models — Session 11')
  }

  return (
    <div className="max-w-4xl space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-white">System Dashboard</h2>
        <button
          onClick={handleRefreshModels}
          className="flex items-center gap-2 text-xs px-3 py-2 rounded bg-gray-800 text-gray-400 hover:text-white transition-colors"
        >
          <RefreshCw size={13} />
          Refresh Models
        </button>
      </div>

      {/* Model Health Cards */}
      <div className="grid grid-cols-3 gap-4">
        {MODEL_ROLES.map(({ role, key, default: defaultModel }) => {
          const healthy = modelHealth[key]
          return (
            <div key={key} className="bg-gray-900 border border-gray-800 rounded-xl p-4">
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs text-gray-500">{role}</span>
                {healthy === true ? (
                  <CheckCircle size={14} className="text-green-400" />
                ) : healthy === false ? (
                  <XCircle size={14} className="text-red-400" />
                ) : (
                  <div className="w-3.5 h-3.5 rounded-full bg-gray-700" />
                )}
              </div>
              <p className="text-sm font-mono text-blue-400">{defaultModel}</p>
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

      {/* STUB notice */}
      <div className="text-xs text-gray-600 border border-gray-800 rounded-lg px-4 py-3">
        Dashboard health pings wired in Session 11. Showing placeholder data.
      </div>
    </div>
  )
}
