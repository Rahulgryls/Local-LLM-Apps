/**
 * LAKO — Confluence Ingestion Page
 * Ingest a single Confluence page by URL into the knowledge base.
 * Session 9: Full implementation.
 * Session 11: Converted to async polling — POST returns job_id, polls status every 2s.
 */

import React, { useState, useRef, useEffect } from 'react'
import { Globe, CheckCircle, XCircle, Loader, RefreshCw, Lock } from 'lucide-react'
import ProgressBar from '../components/ProgressBar'

const PLACEHOLDER_URL = 'https://yourbank.atlassian.net/wiki/spaces/KB/pages/123456'
const POLL_INTERVAL_MS = 2000

export default function ConfluenceIngestion() {
  const [url, setUrl]             = useState('')
  const [apiToken, setApiToken]   = useState('')
  const [showToken, setShowToken] = useState(false)
  const [useMock, setUseMock]     = useState(false)

  const [status, setStatus]         = useState('idle')    // idle | queued | processing | complete | failed
  const [progress, setProgress]     = useState(0)
  const [statusMessage, setStatusMessage] = useState('')
  const [chunksIndexed, setChunksIndexed] = useState(0)
  const [pageTitle, setPageTitle]   = useState('')
  const [errorMsg, setErrorMsg]     = useState('')

  const pollRef = useRef(null)

  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current)
    }
  }, [])

  const stopPolling = () => {
    if (pollRef.current) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }
  }

  const startPolling = (jobId) => {
    stopPolling()
    pollRef.current = setInterval(async () => {
      try {
        const res = await fetch(`/api/ingest/confluence/status?job_id=${jobId}`)
        if (!res.ok) {
          stopPolling()
          setStatus('failed')
          setErrorMsg('Status check failed — see backend logs.')
          return
        }
        const data = await res.json()
        setProgress(data.progress)
        setStatusMessage(data.message)
        if (data.page_title) setPageTitle(data.page_title)

        if (data.status === 'complete') {
          stopPolling()
          setStatus('complete')
          setChunksIndexed(data.chunks_indexed)
        } else if (data.status === 'failed') {
          stopPolling()
          setStatus('failed')
          setErrorMsg(data.error || data.message || 'Ingestion failed.')
        }
      } catch {
        stopPolling()
        setStatus('failed')
        setErrorMsg('Cannot reach backend.')
      }
    }, POLL_INTERVAL_MS)
  }

  const canSubmit = url.trim().length > 0 && !['queued', 'processing'].includes(status)

  const reset = () => {
    stopPolling()
    setStatus('idle')
    setProgress(0)
    setStatusMessage('')
    setChunksIndexed(0)
    setPageTitle('')
    setErrorMsg('')
    setUrl('')
    setApiToken('')
  }

  const handleIngest = async () => {
    if (!canSubmit) return

    setStatus('queued')
    setProgress(3)
    setStatusMessage('Queuing ingestion...')
    setErrorMsg('')
    setChunksIndexed(0)
    setPageTitle('')

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
        setStatus('failed')
        return
      }

      setStatus('processing')
      setProgress(5)
      setStatusMessage('Processing started...')
      startPolling(data.job_id)
    } catch {
      setStatus('failed')
      setErrorMsg('Cannot reach backend. Is the server running?')
    }
  }

  const isActive = status === 'queued' || status === 'processing'

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
            disabled={isActive}
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
            disabled={isActive}
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
          disabled={isActive}
          className="rounded border-gray-600 bg-gray-900 text-blue-600 focus:ring-blue-600"
        />
        Use mock data (test without a real Confluence instance)
      </label>

      {/* Progress bar — shown while processing or after */}
      {status !== 'idle' && status !== 'complete' && status !== 'failed' && (
        <div className="space-y-1">
          <div className="flex justify-between text-xs text-gray-400">
            <span>{statusMessage || 'Processing...'}</span>
            <span>{progress}%</span>
          </div>
          <ProgressBar progress={progress} />
        </div>
      )}

      {/* Success state */}
      {status === 'complete' && (
        <div className="rounded-xl border border-green-800 bg-green-950/30 px-4 py-3 space-y-2">
          <div className="flex items-center gap-2 text-green-400 text-sm font-medium">
            <CheckCircle size={15} />
            Successfully indexed {chunksIndexed} chunk{chunksIndexed !== 1 ? 's' : ''}
          </div>
          <div className="text-xs text-gray-400 space-y-0.5">
            {pageTitle && <p><span className="text-gray-500">Page:</span> {pageTitle}</p>}
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
      {status === 'failed' && (
        <div className="rounded-xl border border-red-800 bg-red-950/30 px-4 py-3 space-y-2">
          <div className="flex items-center gap-2 text-red-400 text-sm font-medium">
            <XCircle size={15} />
            Ingestion failed
          </div>
          <p className="text-xs text-red-300/80">{errorMsg}</p>
          <button
            onClick={() => { stopPolling(); setStatus('idle'); setErrorMsg('') }}
            className="flex items-center gap-1.5 text-xs text-blue-400 hover:text-blue-300 transition-colors"
          >
            <RefreshCw size={11} />
            Try again
          </button>
        </div>
      )}

      {/* Ingest button */}
      {status !== 'complete' && (
        <button
          onClick={handleIngest}
          disabled={!canSubmit}
          className="w-full py-2.5 bg-blue-600 rounded-xl text-sm text-white font-medium hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed transition-colors flex items-center justify-center gap-2"
        >
          {isActive
            ? <><Loader size={14} className="animate-spin" /> Ingesting...</>
            : 'Ingest Page'
          }
        </button>
      )}
    </div>
  )
}
