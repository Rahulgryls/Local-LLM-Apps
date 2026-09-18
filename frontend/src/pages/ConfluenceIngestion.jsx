/**
 * LAKO — Confluence Ingestion Page
 * V1: Ingest a single Confluence page into ChromaDB (legacy).
 * V3: Ingest root page + recursive sub-pages into Qdrant lako_documents.
 */

import React, { useState, useRef, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { Globe, CheckCircle, XCircle, Loader, RefreshCw, Lock, GitBranch, FileText } from 'lucide-react'
import ProgressBar from '../components/ProgressBar'

const PLACEHOLDER_URL = 'https://yourbank.atlassian.net/wiki/spaces/KB/pages/123456'
const POLL_INTERVAL_MS = 2000

// ── V3 Confluence Ingestion (Qdrant / lako_documents) ────────────────────────

function ConfluenceV3Ingestion() {
  const { t } = useTranslation()
  const POLL_MS = 2500

  const [url,            setUrl]            = useState('')
  const [email,          setEmail]          = useState('')
  const [apiToken,       setApiToken]       = useState('')
  const [authType,       setAuthType]       = useState('bearer')  // bearer | basic
  const [crawlSubpages,  setCrawlSubpages]  = useState(true)
  const [status,         setStatus]         = useState('idle')  // idle|queued|crawling|processing|complete|failed
  const [job,            setJob]            = useState(null)
  const [errorMsg,       setErrorMsg]       = useState('')
  const pollRef = useRef(null)

  useEffect(() => () => { if (pollRef.current) clearInterval(pollRef.current) }, [])

  const stopPolling = () => { if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null } }

  const startPolling = (jobId) => {
    stopPolling()
    pollRef.current = setInterval(async () => {
      try {
        const res  = await fetch(`/api/v3/ingest/confluence/${jobId}/status`)
        if (!res.ok) { stopPolling(); setStatus('failed'); setErrorMsg('Status check failed.'); return }
        const data = await res.json()
        setJob(data)
        setStatus(data.status)
        if (data.status === 'complete' || data.status === 'failed') {
          stopPolling()
          if (data.status === 'failed') setErrorMsg(data.error || t('confluence.failed'))
        }
      } catch { stopPolling(); setStatus('failed'); setErrorMsg(t('common.backendError')) }
    }, POLL_MS)
  }

  const handleIngest = async () => {
    if (!url.trim() || ['queued','crawling','processing'].includes(status)) return
    setStatus('queued'); setJob(null); setErrorMsg('')
    try {
      const res = await fetch('/api/v3/ingest/confluence', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({
          url:            url.trim(),
          email:          authType === 'basic' ? (email.trim() || null) : null,
          api_token:      apiToken.trim() || null,
          auth_type:      authType,
          crawl_subpages: crawlSubpages,
        }),
      })
      const data = await res.json()
      if (!res.ok) { setStatus('failed'); setErrorMsg(data.error || `Error ${res.status}`); return }
      setStatus('crawling')
      startPolling(data.job_id)
    } catch { setStatus('failed'); setErrorMsg(t('common.backendError')) }
  }

  const reset = () => {
    stopPolling(); setStatus('idle'); setJob(null); setErrorMsg('')
    setUrl(''); setEmail(''); setApiToken('')
  }


  const isActive  = ['queued','crawling','processing'].includes(status)
  const progress  = !job ? 0
    : status === 'complete' ? 100
    : status === 'crawling' ? 10
    : job.pages_found > 0
      ? Math.round(10 + (job.pages_done / job.pages_found) * 88)
      : 15

  const statusLabel = !job ? t('cfV3.queuing')
    : status === 'crawling'    ? t('cfV3.crawling')
    : status === 'processing'  ? t('cfV3.processingPage', { title: job.current_page || '…', done: job.pages_done, total: job.pages_found })
    : status === 'complete'    ? t('cfV3.done', { pages: job.pages_done, chunks: job.chunks_total })
    : ''

  return (
    <div className="border border-purple-900/40 rounded-xl bg-purple-950/10 p-5 space-y-4">
      {/* Header */}
      <div className="flex items-center gap-2">
        <GitBranch size={15} className="text-purple-400 flex-shrink-0" />
        <div>
          <h3 className="text-sm font-semibold text-white">{t('cfV3.title')}</h3>
          <p className="text-xs text-gray-600 mt-0.5">{t('cfV3.subtitle')}</p>
        </div>
      </div>

      {/* URL */}
      <div className="space-y-1.5">
        <label className="text-xs text-gray-400 font-medium">{t('confluence.urlLabel')}</label>
        <div className="relative">
          <Globe size={14} className="absolute left-3 top-3 text-gray-500 pointer-events-none" />
          <input
            type="url" value={url} onChange={e => setUrl(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && handleIngest()}
            placeholder="https://yourcompany.atlassian.net/wiki/spaces/KB/pages/123456"
            disabled={isActive}
            className="w-full bg-gray-900 border border-gray-700 rounded-xl pl-9 pr-4 py-2.5 text-sm text-gray-100 placeholder-gray-600 focus:outline-none focus:border-purple-600 transition-colors disabled:opacity-50"
          />
        </div>
      </div>

      {/* Auth type selector */}
      <div className="space-y-1.5">
        <label className="text-xs text-gray-400 font-medium">{t('cfV3.authTypeLabel')}</label>
        <div className="flex gap-3">
          {[['bearer', t('cfV3.authBearer')], ['basic', t('cfV3.authBasic')]].map(([val, label]) => (
            <label key={val} className="flex items-center gap-1.5 text-xs text-gray-300 cursor-pointer">
              <input type="radio" name="authType" value={val}
                checked={authType === val} onChange={() => setAuthType(val)}
                disabled={isActive}
                className="text-purple-600 focus:ring-purple-600"
              />
              {label}
            </label>
          ))}
        </div>
        <p className="text-xs text-gray-600">{authType === 'bearer' ? t('cfV3.authBearerHint') : t('cfV3.authBasicHint')}</p>
      </div>

      {/* Email — only for Basic auth */}
      {authType === 'basic' && (
        <div className="space-y-1.5">
          <label className="text-xs text-gray-400 font-medium">{t('cfV3.emailLabel')}</label>
          <input
            type="email" value={email} onChange={e => setEmail(e.target.value)}
            placeholder={t('cfV3.emailPlaceholder')}
            disabled={isActive}
            className="w-full bg-gray-900 border border-gray-700 rounded-xl px-4 py-2.5 text-sm text-gray-100 placeholder-gray-600 focus:outline-none focus:border-purple-600 transition-colors disabled:opacity-50"
          />
        </div>
      )}

      {/* API token */}
      <div className="space-y-1.5">
        <label className="flex items-center gap-1.5 text-xs text-gray-400 font-medium">
          <Lock size={11} />
          {t('cfV3.tokenLabel')}
        </label>
        <input
          type="password" value={apiToken} onChange={e => setApiToken(e.target.value)}
          placeholder={t('confluence.tokenPlaceholder')}
          disabled={isActive}
          className="w-full bg-gray-900 border border-gray-700 rounded-xl px-4 py-2.5 text-sm text-gray-100 placeholder-gray-600 focus:outline-none focus:border-purple-600 transition-colors disabled:opacity-50"
        />
        <p className="text-xs text-gray-600">{t('cfV3.tokenHint')}</p>
      </div>

      {/* Crawl subpages toggle */}
      <label className="flex items-center gap-2 text-xs text-gray-400 cursor-pointer select-none">
        <input type="checkbox" checked={crawlSubpages} onChange={e => setCrawlSubpages(e.target.checked)}
          disabled={isActive}
          className="rounded border-gray-600 bg-gray-900 text-purple-600 focus:ring-purple-600"
        />
        {t('cfV3.crawlSubpages')}
      </label>

      {/* Progress */}
      {isActive && (
        <div className="space-y-1">
          <div className="flex justify-between text-xs text-gray-400">
            <span className="truncate pr-2">{statusLabel}</span>
            <span>{progress}%</span>
          </div>
          <ProgressBar progress={progress} />
          {job && job.pages_found > 0 && (
            <p className="text-xs text-gray-500">{job.pages_done} / {job.pages_found} {t('cfV3.pagesLabel')}</p>
          )}
        </div>
      )}

      {/* Success */}
      {status === 'complete' && job && (
        <div className="rounded-xl border border-green-800 bg-green-950/30 px-4 py-3 space-y-2">
          <div className="flex items-center gap-2 text-green-400 text-sm font-medium">
            <CheckCircle size={15} />
            {t('cfV3.successMsg', { pages: job.pages_done, chunks: job.chunks_total })}
          </div>
          {job.errors.length > 0 && (
            <div className="space-y-0.5">
              <p className="text-xs text-yellow-400">{job.errors.length} {t('cfV3.pagesSkipped')}</p>
              {job.errors.slice(0, 3).map((e, i) => (
                <p key={i} className="text-xs text-gray-500 truncate">{e}</p>
              ))}
            </div>
          )}
          <button onClick={reset}
            className="flex items-center gap-1.5 text-xs text-purple-400 hover:text-purple-300 transition-colors mt-1">
            <RefreshCw size={11} /> {t('confluence.ingestAnother')}
          </button>
        </div>
      )}

      {/* Error */}
      {status === 'failed' && (
        <div className="rounded-xl border border-red-800 bg-red-950/30 px-4 py-3 space-y-2">
          <div className="flex items-center gap-2 text-red-400 text-sm font-medium">
            <XCircle size={15} /> {t('confluence.failed')}
          </div>
          <p className="text-xs text-red-300/80">{errorMsg}</p>
          <button onClick={() => { stopPolling(); setStatus('idle'); setErrorMsg('') }}
            className="flex items-center gap-1.5 text-xs text-purple-400 hover:text-purple-300 transition-colors">
            <RefreshCw size={11} /> {t('confluence.retry')}
          </button>
        </div>
      )}

      {/* Ingest button */}
      {status !== 'complete' && (
        <button onClick={handleIngest}
          disabled={!url.trim() || isActive}
          className="w-full py-2.5 bg-purple-700 rounded-xl text-sm text-white font-medium hover:bg-purple-600 disabled:opacity-40 disabled:cursor-not-allowed transition-colors flex items-center justify-center gap-2">
          {isActive
            ? <><Loader size={14} className="animate-spin" /> {t('confluence.ingesting')}</>
            : t('cfV3.ingestButton')}
        </button>
      )}
    </div>
  )
}

// ── V1 Confluence Ingestion (ChromaDB — legacy) ───────────────────────────────

export default function ConfluenceIngestion() {
  const { t } = useTranslation()

  const [url, setUrl]             = useState('')
  const [apiToken, setApiToken]   = useState('')
  const [showToken, setShowToken] = useState(false)
  const [useMock, setUseMock]     = useState(false)

  const [status, setStatus]               = useState('idle')    // idle | queued | processing | complete | failed
  const [progress, setProgress]           = useState(0)
  const [statusMessage, setStatusMessage] = useState('')
  const [chunksIndexed, setChunksIndexed] = useState(0)
  const [pageTitle, setPageTitle]         = useState('')
  const [errorMsg, setErrorMsg]           = useState('')

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
          setErrorMsg(data.error || data.message || t('confluence.failed'))
        }
      } catch {
        stopPolling()
        setStatus('failed')
        setErrorMsg(t('common.backendError'))
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
      setErrorMsg(t('common.backendError'))
    }
  }

  const isActive = status === 'queued' || status === 'processing'

  return (
    <div className="max-w-2xl space-y-5">
      <div>
        <h2 className="text-lg font-semibold text-white">{t('confluence.title')}</h2>
        <p className="text-sm text-gray-500 mt-1">{t('confluence.subtitle')}</p>
      </div>
      <ConfluenceV3Ingestion />

      {/* URL input */}
      <div className="space-y-1.5">
        <label className="text-xs text-gray-400 font-medium">{t('confluence.urlLabel')}</label>
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
          {showToken ? t('confluence.hideToken') : t('confluence.addToken')}
        </button>
        {showToken && (
          <input
            type="password"
            value={apiToken}
            onChange={e => setApiToken(e.target.value)}
            placeholder={t('confluence.tokenPlaceholder')}
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
        {t('confluence.mockMode')}
      </label>

      {/* Progress bar — shown while processing */}
      {status !== 'idle' && status !== 'complete' && status !== 'failed' && (
        <div className="space-y-1">
          <div className="flex justify-between text-xs text-gray-400">
            <span>{statusMessage || t('confluence.processing')}</span>
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
            {t('confluence.successPrefix')} {chunksIndexed} {chunksIndexed !== 1 ? t('confluence.chunks') : t('confluence.chunk')}
          </div>
          <div className="text-xs text-gray-400 space-y-0.5">
            {pageTitle && (
              <p>
                <span className="text-gray-500">{t('confluence.page')}:</span> {pageTitle}
              </p>
            )}
          </div>
          <button
            onClick={reset}
            className="flex items-center gap-1.5 text-xs text-blue-400 hover:text-blue-300 transition-colors mt-1"
          >
            <RefreshCw size={11} />
            {t('confluence.ingestAnother')}
          </button>
        </div>
      )}

      {/* Error state */}
      {status === 'failed' && (
        <div className="rounded-xl border border-red-800 bg-red-950/30 px-4 py-3 space-y-2">
          <div className="flex items-center gap-2 text-red-400 text-sm font-medium">
            <XCircle size={15} />
            {t('confluence.failed')}
          </div>
          <p className="text-xs text-red-300/80">{errorMsg}</p>
          <button
            onClick={() => { stopPolling(); setStatus('idle'); setErrorMsg('') }}
            className="flex items-center gap-1.5 text-xs text-blue-400 hover:text-blue-300 transition-colors"
          >
            <RefreshCw size={11} />
            {t('confluence.retry')}
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
            ? <><Loader size={14} className="animate-spin" /> {t('confluence.ingesting')}</>
            : t('confluence.ingestButton')
          }
        </button>
      )}
    </div>
  )
}
