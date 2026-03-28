/**
 * LAKO — Vector Database Status Page
 * Shows ChromaDB health, chunk count, collection info.
 * Session 1: Shell — full implementation in Session 4.
 */

import React, { useState } from 'react'
import { Database, RefreshCw } from 'lucide-react'

export default function VectorDB() {
  const [stats] = useState({
    status: 'stub',
    collection_count: 0,
    total_chunks: 0,
    chromadb_path: '/lako/storage/chromadb',
    message: 'ChromaDB wired in Session 4.',
  })

  return (
    <div className="max-w-2xl space-y-5">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-white">Vector Database</h2>
        <button className="flex items-center gap-2 text-xs px-3 py-2 rounded bg-gray-800 text-gray-400 hover:text-white transition-colors">
          <RefreshCw size={12} />
          Refresh
        </button>
      </div>

      <div className="grid grid-cols-2 gap-4">
        {[
          { label: 'Status',        value: stats.status },
          { label: 'Total Chunks',  value: stats.total_chunks },
          { label: 'Collections',   value: stats.collection_count },
          { label: 'Engine',        value: 'ChromaDB (local)' },
        ].map(({ label, value }) => (
          <div key={label} className="bg-gray-900 border border-gray-800 rounded-xl p-4">
            <p className="text-xs text-gray-500 mb-1">{label}</p>
            <p className="text-lg font-semibold text-white">{value}</p>
          </div>
        ))}
      </div>

      <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
        <div className="flex items-center gap-2 mb-2">
          <Database size={14} className="text-blue-400" />
          <span className="text-sm text-gray-300">Storage Path</span>
        </div>
        <code className="text-xs text-blue-400 font-mono">{stats.chromadb_path}</code>
      </div>

      <p className="text-xs text-gray-600">[STUB] {stats.message}</p>
    </div>
  )
}
