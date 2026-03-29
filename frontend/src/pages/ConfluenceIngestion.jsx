/**
 * LAKO — Confluence Ingestion Page
 * Ingest a single Confluence page by URL into the knowledge base.
 * Session 9: Full implementation.
 */

import React, { useState } from 'react'
import { Globe, CheckCircle, XCircle, Loader, RefreshCw, Lock } from 'lucide-react'
import ProgressBar from '../components/ProgressBar'

const PLACEHOLDER_URL = 'https://yourbank.atlassian.net/wiki/spaces/KB/pages/123456'

export default function ConfluenceIngestion() {
  const [url, setUrl]               = useState('')
  const [apiToken, setApiToken]     = useState('')
  const [showToken, setShowToken]   = useState(false)
  const [useMock, setUseMock]       = useState(false)
  const [status, setStatus]         = useState('idle')   // idle | loading | success | error
  const [result, setResult]         = useState(null)     // ConfluenceIngestResponse
  const [errorMsg, setErrorMsg]     = useState('')

  const isLoading = status === 'loading'
  const canSubmit = url.trim().length > 0 && !isLoading

  const reset = () => {
    setStatus('idle')
    setResult(null)
    setErrorMsg('')
    setUrl('')
    setApiToken('')
  }

  const handleIngest = async () => {
    if (!canSubmit) return

    setStatus('loading')
    setResult(null)
    setErrorMsg('')

    try {
      const res = await fetch('/api/ingest/confluence', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({
          url:       url.trim(),
          api_token: apiToken.trim() || null,
          mock:      useMock,
        }),
      })

      const data = await res.json()

      if (!res.ok) {
        setErrorMsg(data.error || `Server error ${res.status}`)
        setStatus('error')
        return
      }

      setResult(data)
      setStatus('success')
    } catch (err) {
      setErrorMsg('Cannot reach backend. Is the server running?')
      setStatus('error')
    }
  }

  return (
    <div className="max-w-2xl space-y-5">
      <div>
        <h2 className="text-lg font-semibold text-white">Confluence Page Ingestion</h2>
        <p className="text-sm text-gray-500 mt-1">
          Enter the URL of a Confluence page to fetch, parse, and index its content into the knowledge base.
        </p>
      </div>

      {/* URL input */}
      <div className="space-y-1.5">
        <label className="text-xs text-gray-400 font-medium">Confluence Page URL</label>
        <div className="relative">
          <Globe size={14} className="absolute left-3 top-3 text-gray-500 pointer-events-none" />
          <input
            type="url"
            value={url}
            onChange={e => setUrl(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && handleIngest()}
            placeholder={PLACEHOLDER_URL}
            disabled={isLoading}
            className="w-full bg-gray-900 border border-gray-700 rounded-xl pl-9 pr-4 py-2.5 text-sm text-gray-100 placeholder-gray-600 focus:outline-none focus:border-blue-600 transition-colors disabled:opacity-50"
          />
        </div>
      </div>

      {/* API token (collapsible) */}
      <div className="space-y-1.5">
        <button
          type="button"
          onClick={() => setShowToken(v => !v)}
          className="flex items-center gap-1.5 text-xs text-gray-500 hover:text-gray-300 transition-colors"
        >
          <Lock size={11} />
          {showToken ? 'Hide API token' : 'Add API token (for private pages)'}
        </button>
        {showToken && (
          <input
            type="password"
            value={apiToken}
            onChange={e => setApiToken(e.target.value)}
            placeholder="Bearer token or personal access token"
            disabled={isLoading}
            className="w-full bg-gray-900 border border-gray-700 rounded-xl px-4 py-2.5 text-sm text-gray-100 placeholder-gray-600 focus:outline-none focus:border-blue-600 transition-colors disabled:opacity-50"
          />
        )}
      </div>

      {/* Mock mode toggle */}
      <label className="flex items-center gap-2 text-xs text-gray-500 cursor-pointer select-none">
        <input
          type="checkbox"
          checked={useMock}
          onChange={e => setUseMock(e.target.checked)}
          disabled={isLoading}
          className="rounded border-gray-600 bg-gray-900 text-blue-600 focus:ring-blue-600"
        />
        Use mock data (test without a real Confluence instance)
      </label>

      {/* Progress bar — shown while loading */}
      {isLoading && (
        <div className="space-y-1">
          <div className="flex justify-between text-xs text-gray-400">
            <span>Fetching and indexing page...</span>
          </div>
          {/* Indeterminate shimmer — we don't get streaming progress from this endpoint */}
          <div className="h-2 rounded-full bg-gray-800 overflow-hidden">
            <div className="h-full bg-blue-600 rounded-full animate-pulse w-1/2" />
          </div>
        </div>
      )}

      {/* Success state */}
      {status === 'success' && result && (
        <div className="rounded-xl border border-green-800 bg-green-950/30 px-4 py-3 space-y-2">
          <div className="flex items-center gap-2 text-green-400 text-sm font-medium">
            <CheckCircle size={15} />
            Successfully indexed {result.chunks_indexed} chunk{result.chunks_indexed !== 1 ? 's' : ''}
          </div>
          <div className="text-xs text-gray-400 space-y-0.5">
            <p><span className="text-gray-500">Page:</span> {result.page_title}</p>
            <p><span className="text-gray-500">ID:</span> {result.page_id}</p>
            <p><span className="text-gray-500">Time:</span> {result.processing_time}s</p>
          </div>
          <button
            onClick={reset}
            className="flex items-center gap-1.5 text-xs text-blue-400 hover:text-blue-300 transition-colors mt-1"
          >
            <RefreshCw size={11} />
            Ingest another page
          </button>
        </div>
      )}

      {/* Error state */}
      {status === 'error' && (
        <div className="rounded-xl border border-red-800 bg-red-950/30 px-4 py-3 space-y-2">
          <div className="flex items-center gap-2 text-red-400 text-sm font-medium">
            <XCircle size={15} />
            Ingestion failed
          </div>
          <p className="text-xs text-red-300/80">{errorMsg}</p>
          <button
            onClick={() => { setStatus('idle'); setErrorMsg('') }}
            className="flex items-center gap-1.5 text-xs text-blue-400 hover:text-blue-300 transition-colors"
          >
            <RefreshCw size={11} />
            Try again
          </button>
        </div>
      )}

      {/* Ingest button */}
      {status !== 'success' && (
        <button
          onClick={handleIngest}
          disabled={!canSubmit}
          className="w-full py-2.5 bg-blue-600 rounded-xl text-sm text-white font-medium hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed transition-colors flex items-center justify-center gap-2"
        >
          {isLoading
            ? <><Loader size={14} className="animate-spin" /> Ingesting...</>
            : 'Ingest Page'
          }
        </button>
      )}
    </div>
  )
}
