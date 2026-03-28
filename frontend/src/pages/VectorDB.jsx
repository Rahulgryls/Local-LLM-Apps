/**
 * LAKO — Vector Database Status Page
 * Shows live ChromaDB health, chunk count, collection info.
 * Clear Collection button calls DELETE /api/vector/clear.
 * Session 4: Fully wired.
 */

import React, { useState, useEffect } from 'react'
import { Database, RefreshCw, Trash2, AlertTriangle } from 'lucide-react'

export default function VectorDB() {
  const [stats, setStats]           = useState(null)
  const [loading, setLoading]       = useState(false)
  const [clearing, setClearing]     = useState(false)
  const [confirmClear, setConfirmClear] = useState(false)
  const [clearMsg, setClearMsg]     = useState('')

  const fetchStats = async () => {
    setLoading(true)
    try {
      const res = await fetch('/api/vector/status')
      const data = await res.json()
      setStats(data)
    } catch (err) {
      console.error('[VectorDB] Failed to fetch stats:', err)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchStats()
  }, [])

  const handleClear = async () => {
    if (!confirmClear) {
      setConfirmClear(true)
      return
    }
    setClearing(true)
    setConfirmClear(false)
    setClearMsg('')
    try {
      const res = await fetch('/api/vector/clear', { method: 'DELETE' })
      const data = await res.json()
      setClearMsg(`Cleared ${data.deleted_chunks} chunk${data.deleted_chunks !== 1 ? 's' : ''}.`)
      await fetchStats()
    } catch (err) {
      setClearMsg('Clear failed — check backend logs.')
    } finally {
      setClearing(false)
    }
  }

  const statusColor = stats?.status === 'ok'
    ? 'text-green-400'
    : stats?.status === 'error'
    ? 'text-red-400'
    : 'text-gray-400'

  return (
    <div className="max-w-2xl space-y-5">

      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-white">Vector Database</h2>
        <button
          onClick={fetchStats}
          disabled={loading}
          className="flex items-center gap-2 text-xs px-3 py-2 rounded bg-gray-800 text-gray-400 hover:text-white disabled:opacity-50 transition-colors"
        >
          <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
          Refresh
        </button>
      </div>

      {/* Stats grid */}
      <div className="grid grid-cols-2 gap-4">
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
          <p className="text-xs text-gray-500 mb-1">Status</p>
          <p className={`text-lg font-semibold ${statusColor}`}>
            {stats ? stats.status : '…'}
          </p>
        </div>
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
          <p className="text-xs text-gray-500 mb-1">Total Chunks</p>
          <p className="text-lg font-semibold text-white">
            {stats ? stats.total_chunks.toLocaleString() : '…'}
          </p>
        </div>
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
          <p className="text-xs text-gray-500 mb-1">Collection</p>
          <p className="text-sm font-mono text-blue-400 truncate">
            {stats ? stats.collection : '…'}
          </p>
        </div>
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
          <p className="text-xs text-gray-500 mb-1">Engine</p>
          <p className="text-lg font-semibold text-white">ChromaDB</p>
        </div>
      </div>

      {/* Storage path */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
        <div className="flex items-center gap-2 mb-2">
          <Database size={14} className="text-blue-400" />
          <span className="text-sm text-gray-300">Storage Path</span>
        </div>
        <code className="text-xs text-blue-400 font-mono break-all">
          {stats ? stats.chromadb_path : '…'}
        </code>
      </div>

      {/* Clear Collection */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl p-4 space-y-3">
        <div className="flex items-center gap-2">
          <Trash2 size={14} className="text-red-400" />
          <span className="text-sm text-gray-300">Clear Collection</span>
        </div>
        <p className="text-xs text-gray-500">
          Permanently deletes all ingested document chunks. This cannot be undone.
          You will need to re-ingest all documents.
        </p>

        {confirmClear && (
          <div className="flex items-center gap-2 text-xs text-yellow-400 bg-yellow-400/10 border border-yellow-400/20 rounded-lg px-3 py-2">
            <AlertTriangle size={12} />
            Click again to confirm — this will delete all {stats?.total_chunks ?? 0} chunks.
          </div>
        )}

        {clearMsg && (
          <p className="text-xs text-gray-400">{clearMsg}</p>
        )}

        <button
          onClick={handleClear}
          disabled={clearing || stats?.total_chunks === 0}
          className={`flex items-center gap-2 text-xs px-4 py-2 rounded-lg transition-colors disabled:opacity-40 disabled:cursor-not-allowed ${
            confirmClear
              ? 'bg-red-600 text-white hover:bg-red-500'
              : 'bg-gray-800 text-red-400 hover:bg-gray-700'
          }`}
        >
          <Trash2 size={12} />
          {clearing ? 'Clearing…' : confirmClear ? 'Confirm — delete all chunks' : 'Clear Collection'}
        </button>
      </div>
    </div>
  )
}
