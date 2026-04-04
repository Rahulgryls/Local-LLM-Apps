/**
 * LAKO — CacheRefreshButton
 * Displays cached query count and lets the user clear the RAG cache.
 * Session 22: Created.
 */

import React, { useState, useEffect, useCallback } from 'react'
import { RotateCcw } from 'lucide-react'

export default function CacheRefreshButton({ disabled = false }) {
  const [count, setCount]       = useState(null)   // null = loading
  const [clearing, setClearing] = useState(false)
  const [toast, setToast]       = useState(null)   // { cleared: N } | null

  const fetchStats = useCallback(() => {
    fetch('/api/cache/stats')
      .then(r => r.json())
      .then(d => setCount(d.cached_queries ?? 0))
      .catch(() => setCount(null))
  }, [])

  // Poll on mount + every 30 s
  useEffect(() => {
    fetchStats()
    const id = setInterval(fetchStats, 30_000)
    return () => clearInterval(id)
  }, [fetchStats])

  const handleClear = async () => {
    if (clearing || disabled || !count) return
    setClearing(true)
    try {
      const res = await fetch('/api/cache', { method: 'DELETE' })
      const data = await res.json()
      setCount(0)
      setToast({ cleared: data.cleared ?? 0 })
      setTimeout(() => setToast(null), 2500)
    } catch {
      // silently ignore
    } finally {
      setClearing(false)
    }
  }

  const hasCache = count !== null && count > 0
  const btnDisabled = disabled || clearing || !hasCache

  return (
    <div className="relative flex items-center">
      <button
        onClick={handleClear}
        disabled={btnDisabled}
        title={hasCache ? `Clear ${count} cached quer${count === 1 ? 'y' : 'ies'}` : 'Cache is empty'}
        className={`flex items-center gap-1.5 text-xs px-2 py-1.5 rounded-lg border transition-colors
          ${hasCache && !disabled
            ? 'border-amber-600/50 text-amber-400 hover:bg-amber-600/10 cursor-pointer'
            : 'border-gray-700 text-gray-600 cursor-not-allowed opacity-50'
          }`}
      >
        <RotateCcw
          size={12}
          className={clearing ? 'animate-spin' : ''}
        />
        {count === null ? '…' : count > 0 ? `${count} cached` : 'No cache'}
      </button>

      {/* Success toast */}
      {toast && (
        <div className="absolute bottom-full mb-2 left-1/2 -translate-x-1/2 whitespace-nowrap text-xs text-green-400 bg-gray-900 border border-green-600/40 rounded-lg px-3 py-1.5 shadow-lg pointer-events-none">
          Cleared {toast.cleared} cached quer{toast.cleared === 1 ? 'y' : 'ies'}
        </div>
      )}
    </div>
  )
}
