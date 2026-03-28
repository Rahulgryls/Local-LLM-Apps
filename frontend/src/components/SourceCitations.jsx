/**
 * LAKO — Source Citations Component
 * Displays source chunks returned with each RAG answer.
 * Shows: filename, page number, chunk type, relevance score.
 * Session 1: Shell — wired in Session 8.
 */

import React, { useState } from 'react'
import { ChevronDown, ChevronUp, FileText } from 'lucide-react'

export default function SourceCitations({ sources = [] }) {
  const [expanded, setExpanded] = useState(false)

  if (!sources || sources.length === 0) return null

  return (
    <div className="mt-3 border border-gray-700 rounded-lg overflow-hidden">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between px-4 py-2.5 bg-gray-800 text-xs text-gray-400 hover:text-white transition-colors"
      >
        <span className="flex items-center gap-2">
          <FileText size={13} />
          {sources.length} source{sources.length !== 1 ? 's' : ''} used
        </span>
        {expanded ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
      </button>

      {expanded && (
        <div className="divide-y divide-gray-800">
          {sources.map((src, i) => (
            <div key={i} className="px-4 py-3 bg-gray-900 text-xs">
              <div className="flex items-center justify-between mb-1">
                <span className="text-gray-300 font-medium">{src.filename}</span>
                <span className="text-gray-500">p.{src.page} · {src.chunk_type}</span>
              </div>
              <p className="text-gray-500 line-clamp-2">{src.content}</p>
              <span className="text-blue-500 mt-1 block">
                score: {(src.score * 100).toFixed(1)}%
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
