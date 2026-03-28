/**
 * LAKO — Confluence Ingestion Page
 * Ingest a single Confluence page by URL.
 * Session 1: Shell — full implementation in Session 9.
 */

import React, { useState } from 'react'
import { Globe, CheckCircle, Loader } from 'lucide-react'

export default function ConfluenceIngestion() {
  const [url, setUrl] = useState('')
  const [status, setStatus] = useState('idle') // idle / loading / done / error
  const [message, setMessage] = useState('')

  const handleIngest = async () => {
    if (!url.trim()) return
    setStatus('loading')
    setMessage('')

    try {
      // TODO (Session 9): POST to /api/ingest/confluence
      await new Promise(r => setTimeout(r, 600))
      setMessage('[STUB] Confluence ingestion wired in Session 9.')
      setStatus('done')
    } catch (err) {
      setMessage('Error: ' + err.message)
      setStatus('error')
    }
  }

  return (
    <div className="max-w-2xl space-y-5">
      <h2 className="text-lg font-semibold text-white">Confluence Page Ingestion</h2>
      <p className="text-sm text-gray-500">
        Enter the full URL of a Confluence page to extract and index its content.
      </p>

      <div className="flex gap-3">
        <div className="flex-1 relative">
          <Globe size={14} className="absolute left-3 top-3 text-gray-500" />
          <input
            type="url"
            value={url}
            onChange={e => setUrl(e.target.value)}
            placeholder="https://yourbank.atlassian.net/wiki/spaces/..."
            className="w-full bg-gray-900 border border-gray-700 rounded-xl pl-9 pr-4 py-2.5 text-sm text-gray-100 placeholder-gray-600 focus:outline-none focus:border-blue-600 transition-colors"
          />
        </div>
        <button
          onClick={handleIngest}
          disabled={!url.trim() || status === 'loading'}
          className="px-5 py-2.5 bg-blue-600 rounded-xl text-sm text-white hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          {status === 'loading' ? <Loader size={14} className="animate-spin" /> : 'Ingest'}
        </button>
      </div>

      {message && (
        <div className={`flex items-center gap-2 text-sm ${status === 'done' ? 'text-green-400' : 'text-red-400'}`}>
          <CheckCircle size={14} />
          {message}
        </div>
      )}
    </div>
  )
}
