/**
 * LAKO — Vector Database Status Page
 * V1: ChromaDB health, chunk count, clear collection.
 * V2: Qdrant health, document count, clear all V2 data (Qdrant + SQLite).
 * Session 4: Fully wired (V1).
 * Session 16: V2 section added.
 */

import React, { useState, useEffect } from 'react'
import { Database, RefreshCw, Trash2, AlertTriangle, Zap } from 'lucide-react'

// ── V1 ChromaDB Section ───────────────────────────────────────────────────────

function V1Section() {
  const [stats, setStats]           = useState(null)
  const [loading, setLoading]       = useState(false)
  const [clearing, setClearing]     = useState(false)
  const [confirmClear, setConfirmClear] = useState(false)
  const [clearMsg, setClearMsg]     = useState('')

  const fetchStats = async () => {
    setLoading(true)
    try {
      const res = await fetch('/api/vector/status')
      setStats(await res.json())
    } catch {}
    finally { setLoading(false) }
  }

  useEffect(() => { fetchStats() }, [])

  const handleClear = async () => {
    if (!confirmClear) { setConfirmClear(true); return }
    setClearing(true); setConfirmClear(false); setClearMsg('')
    try {
      const res  = await fetch('/api/vector/clear', { method: 'DELETE' })
      const data = await res.json()
      setClearMsg(`Cleared ${data.deleted_chunks} chunk${data.deleted_chunks !== 1 ? 's' : ''}.`)
      await fetchStats()
    } catch { setClearMsg('Clear failed — check backend logs.') }
    finally { setClearing(false) }
  }

  const statusColor = stats?.status === 'ok' ? 'text-green-400'
    : stats?.status === 'error' ? 'text-red-400' : 'text-gray-400'

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Database size={15} className="text-blue-400" />
          <h3 className="text-sm font-semibold text-white">V1 Index — ChromaDB</h3>
        </div>
        <button onClick={fetchStats} disabled={loading}
          className="flex items-center gap-2 text-xs px-3 py-1.5 rounded bg-gray-800 text-gray-400 hover:text-white disabled:opacity-50 transition-colors">
          <RefreshCw size={11} className={loading ? 'animate-spin' : ''} /> Refresh
        </button>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div className="bg-gray-800/60 rounded-lg p-3">
          <p className="text-xs text-gray-500 mb-1">Status</p>
          <p className={`text-base font-semibold ${statusColor}`}>{stats ? stats.status : '…'}</p>
        </div>
        <div className="bg-gray-800/60 rounded-lg p-3">
          <p className="text-xs text-gray-500 mb-1">Total Chunks</p>
          <p className="text-base font-semibold text-white">{stats ? stats.total_chunks.toLocaleString() : '…'}</p>
        </div>
        <div className="bg-gray-800/60 rounded-lg p-3">
          <p className="text-xs text-gray-500 mb-1">Collection</p>
          <p className="text-xs font-mono text-blue-400 truncate">{stats ? stats.collection : '…'}</p>
        </div>
        <div className="bg-gray-800/60 rounded-lg p-3">
          <p className="text-xs text-gray-500 mb-1">Engine</p>
          <p className="text-base font-semibold text-white">ChromaDB</p>
        </div>
      </div>

      <div className="bg-gray-800/60 rounded-lg p-3">
        <p className="text-xs text-gray-500 mb-1">Storage Path</p>
        <code className="text-xs text-blue-400 font-mono break-all">{stats ? stats.chromadb_path : '…'}</code>
      </div>

      <div className="space-y-3">
        <div className="flex items-center gap-2">
          <Trash2 size={13} className="text-red-400" />
          <span className="text-sm text-gray-300">Clear Collection</span>
        </div>
        <p className="text-xs text-gray-500">
          Permanently deletes all V1 ingested chunks from ChromaDB. Documents must be re-ingested.
        </p>
        {confirmClear && (
          <div className="flex items-center gap-2 text-xs text-yellow-400 bg-yellow-400/10 border border-yellow-400/20 rounded-lg px-3 py-2">
            <AlertTriangle size={12} />
            Click again to confirm — this will delete all {stats?.total_chunks ?? 0} chunks.
          </div>
        )}
        {clearMsg && <p className="text-xs text-gray-400">{clearMsg}</p>}
        <button onClick={handleClear} disabled={clearing || stats?.total_chunks === 0}
          className={`flex items-center gap-2 text-xs px-4 py-2 rounded-lg transition-colors disabled:opacity-40 disabled:cursor-not-allowed ${
            confirmClear ? 'bg-red-600 text-white hover:bg-red-500' : 'bg-gray-800 text-red-400 hover:bg-gray-700'
          }`}>
          <Trash2 size={12} />
          {clearing ? 'Clearing…' : confirmClear ? 'Confirm — delete all chunks' : 'Clear V1 Collection'}
        </button>
      </div>
    </div>
  )
}

// ── V2 Qdrant + SQLite Section ────────────────────────────────────────────────

function V2Section() {
  const [health,   setHealth]   = useState(null)
  const [docs,     setDocs]     = useState(null)
  const [loading,  setLoading]  = useState(false)
  const [clearing, setClearing] = useState(false)
  const [confirm,  setConfirm]  = useState(false)
  const [msg,      setMsg]      = useState('')

  const fetchStats = async () => {
    setLoading(true)
    try {
      const [h, d] = await Promise.all([
        fetch('/api/v2/health').then(r => r.json()),
        fetch('/api/v2/documents').then(r => r.json()),
      ])
      setHealth(h)
      setDocs(d.documents || [])
    } catch {}
    finally { setLoading(false) }
  }

  useEffect(() => { fetchStats() }, [])

  const handleClear = async () => {
    if (!confirm) { setConfirm(true); return }
    setClearing(true); setConfirm(false); setMsg('')
    try {
      const res  = await fetch('/api/v2/clear', { method: 'DELETE' })
      const data = await res.json()
      setMsg(`Cleared ${data.deleted_docs} document${data.deleted_docs !== 1 ? 's' : ''} and ${data.deleted_points} vectors.`)
      await fetchStats()
    } catch { setMsg('Clear failed — check backend logs.') }
    finally { setClearing(false) }
  }

  const isEmpty = (health?.points_count ?? 0) === 0 && (docs?.length ?? 0) === 0

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Zap size={15} className="text-blue-400" />
          <h3 className="text-sm font-semibold text-white">V2 Index — Qdrant + SQLite</h3>
        </div>
        <button onClick={fetchStats} disabled={loading}
          className="flex items-center gap-2 text-xs px-3 py-1.5 rounded bg-gray-800 text-gray-400 hover:text-white disabled:opacity-50 transition-colors">
          <RefreshCw size={11} className={loading ? 'animate-spin' : ''} /> Refresh
        </button>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div className="bg-gray-800/60 rounded-lg p-3">
          <p className="text-xs text-gray-500 mb-1">Status</p>
          <p className={`text-base font-semibold ${health?.qdrant_status === 'CollectionStatus.GREEN' || health?.qdrant_status?.includes('green') ? 'text-green-400' : health ? 'text-yellow-400' : 'text-gray-400'}`}>
            {health ? 'ok' : '…'}
          </p>
        </div>
        <div className="bg-gray-800/60 rounded-lg p-3">
          <p className="text-xs text-gray-500 mb-1">Qdrant Vectors</p>
          <p className="text-base font-semibold text-white">{health ? (health.points_count ?? 0).toLocaleString() : '…'}</p>
        </div>
        <div className="bg-gray-800/60 rounded-lg p-3">
          <p className="text-xs text-gray-500 mb-1">Documents (SQLite)</p>
          <p className="text-base font-semibold text-white">{docs !== null ? docs.length : '…'}</p>
        </div>
        <div className="bg-gray-800/60 rounded-lg p-3">
          <p className="text-xs text-gray-500 mb-1">Engine</p>
          <p className="text-base font-semibold text-white">Qdrant</p>
        </div>
      </div>

      {docs && docs.length > 0 && (
        <div className="bg-gray-800/60 rounded-lg p-3 space-y-1.5">
          <p className="text-xs text-gray-500 mb-2">Indexed Documents</p>
          {docs.map(d => (
            <div key={d.doc_id} className="flex items-center justify-between text-xs">
              <span className="text-gray-300 truncate flex-1">{d.filename}</span>
              <span className="text-gray-600 ml-3 flex-shrink-0">{d.total_pages}p</span>
            </div>
          ))}
        </div>
      )}

      <div className="space-y-3">
        <div className="flex items-center gap-2">
          <Trash2 size={13} className="text-red-400" />
          <span className="text-sm text-gray-300">Clear V2 Index</span>
        </div>
        <p className="text-xs text-gray-500">
          Permanently deletes all V2 data — Qdrant vectors, SQLite documents, pages, and summaries.
          The query cache is also cleared. Documents must be re-ingested.
        </p>
        {confirm && (
          <div className="flex items-center gap-2 text-xs text-yellow-400 bg-yellow-400/10 border border-yellow-400/20 rounded-lg px-3 py-2">
            <AlertTriangle size={12} />
            Click again to confirm — this will delete {docs?.length ?? 0} documents and {health?.points_count ?? 0} vectors.
          </div>
        )}
        {msg && <p className="text-xs text-gray-400">{msg}</p>}
        <button onClick={handleClear} disabled={clearing || isEmpty}
          className={`flex items-center gap-2 text-xs px-4 py-2 rounded-lg transition-colors disabled:opacity-40 disabled:cursor-not-allowed ${
            confirm ? 'bg-red-600 text-white hover:bg-red-500' : 'bg-gray-800 text-red-400 hover:bg-gray-700'
          }`}>
          <Trash2 size={12} />
          {clearing ? 'Clearing…' : confirm ? 'Confirm — delete all V2 data' : 'Clear V2 Index'}
        </button>
      </div>
    </div>
  )
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function VectorDB() {
  return (
    <div className="max-w-2xl space-y-6">
      <h2 className="text-lg font-semibold text-white">Vector Database</h2>

      <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
        <V1Section />
      </div>

      <div className="bg-gray-900 border border-blue-900/40 rounded-xl p-5">
        <V2Section />
      </div>
    </div>
  )
}
