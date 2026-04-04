/**
 * LAKO — Document Ingestion Page
 * V1: POST /api/ingest/docs — PDF, TXT, XLSX, DOCX, PPTX (chunked, ChromaDB).
 * V2: POST /api/v2/ingest  — PDF, PPTX only (full-page → LLM summary → Qdrant).
 * Session 5: Fully wired (V1).
 * Session 12: Full i18n (EN + NL).
 * Session 15 (V2 Session 5): Added V2 Smart Index section below V1 uploader.
 */

import React, { useState, useRef, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { Upload, FileText, CheckCircle, XCircle, Eye, Brain, ChevronRight } from 'lucide-react'
import ProgressBar from '../components/ProgressBar'

const ACCEPTED_TYPES    = '.pdf,.txt,.xlsx,.docx,.pptx'
const V2_ACCEPTED_TYPES = '.pdf,.pptx'

// ── V2 phase label helper ─────────────────────────────────────────────────────
function v2PhaseLabel(phase, pagesProcessed, totalPages, t) {
  if (phase === 'extracting')  return t('v2.ingest.phaseExtracting')
  if (phase === 'summarizing') {
    if (totalPages) return t('v2.ingest.phaseSummarizing', { current: pagesProcessed, total: totalPages })
    return t('v2.ingest.phaseExtracting')
  }
  if (phase === 'embedding')   return t('v2.ingest.phaseEmbedding')
  if (phase === 'complete')    return t('v2.ingest.phaseReady')
  if (phase === 'failed')      return t('v2.ingest.phaseFailed')
  return t('v2.ingest.ingesting')
}

function v2PhaseProgress(phase, pagesProcessed, totalPages) {
  if (phase === 'extracting')  return 10
  if (phase === 'summarizing') {
    if (totalPages) return Math.round(10 + 75 * (pagesProcessed / totalPages))
    return 20
  }
  if (phase === 'embedding')   return 90
  if (phase === 'complete')    return 100
  return 5
}

// ── V2 ingestion section ──────────────────────────────────────────────────────
function V2IngestSection() {
  const { t } = useTranslation()
  const fileRef  = useRef(null)
  const pollRef  = useRef(null)

  const [file,        setFile]        = useState(null)
  const [status,      setStatus]      = useState('idle')   // idle|uploading|processing|complete|failed
  const [phase,       setPhase]       = useState('')
  const [pagesProc,   setPagesProc]   = useState(0)
  const [totalPages,  setTotalPages]  = useState(null)
  const [errorMsg,    setErrorMsg]    = useState('')
  const [v2Docs,      setV2Docs]      = useState([])
  const [jobId,       setJobId]       = useState(null)

  const stopPolling = () => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
  }

  // fetch V2 doc list
  const refreshDocs = () => {
    fetch('/api/v2/documents')
      .then(r => r.json())
      .then(d => setV2Docs(d.documents || []))
      .catch(() => {})
  }

  useEffect(() => {
    refreshDocs()
    return () => stopPolling()
  }, [])

  const startPolling = (id) => {
    stopPolling()
    pollRef.current = setInterval(async () => {
      try {
        const res  = await fetch(`/api/v2/ingest/${id}/status`)
        const data = await res.json()
        setPhase(data.phase || '')
        setPagesProc(data.pages_processed || 0)
        setTotalPages(data.total_pages || null)

        if (data.status === 'ready') {
          stopPolling()
          setStatus('complete')
          refreshDocs()
        } else if (data.status === 'failed') {
          stopPolling()
          setStatus('failed')
          setErrorMsg(data.error || t('v2.ingest.phaseFailed'))
        }
      } catch {
        stopPolling()
        setStatus('failed')
        setErrorMsg(t('common.backendError'))
      }
    }, 2000)
  }

  const handleFileSelect = (e) => {
    const f = e.target.files[0]
    if (f) { setFile(f); setStatus('idle'); setErrorMsg('') }
  }

  const handleDrop = (e) => {
    e.preventDefault()
    const f = e.dataTransfer.files[0]
    if (f) { setFile(f); setStatus('idle'); setErrorMsg('') }
  }

  const handleIngest = async () => {
    if (!file) return
    setStatus('uploading')
    setPhase('uploading')
    setErrorMsg('')
    setPagesProc(0)
    setTotalPages(null)

    const formData = new FormData()
    formData.append('file', file)

    try {
      const res = await fetch('/api/v2/ingest', { method: 'POST', body: formData })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        setStatus('failed')
        setErrorMsg(err.detail || t('documents.failed'))
        return
      }
      const data = await res.json()
      setJobId(data.job_id)
      setStatus('processing')
      startPolling(data.job_id)
    } catch {
      setStatus('failed')
      setErrorMsg(t('common.backendError'))
    }
  }

  const isActive   = status === 'uploading' || status === 'processing'
  const progress   = v2PhaseProgress(phase, pagesProc, totalPages)
  const phaseLabel = v2PhaseLabel(phase, pagesProc, totalPages, t)

  return (
    <div className="border border-blue-900/40 rounded-xl bg-blue-950/10 p-5 space-y-4">
      {/* Section header */}
      <div className="flex items-center gap-2">
        <Brain size={15} className="text-blue-400 flex-shrink-0" />
        <div>
          <h3 className="text-sm font-semibold text-white">{t('v2.ingest.title')}</h3>
          <p className="text-xs text-gray-600 mt-0.5">{t('v2.ingest.subtitle')}</p>
        </div>
      </div>

      {/* Drop zone */}
      <div
        onDrop={handleDrop}
        onDragOver={e => e.preventDefault()}
        onClick={() => !isActive && fileRef.current?.click()}
        className={`border-2 border-dashed rounded-xl p-7 text-center transition-colors ${
          isActive
            ? 'border-gray-800 cursor-not-allowed opacity-60'
            : 'border-gray-700 cursor-pointer hover:border-blue-600'
        }`}
      >
        <Upload size={22} className="text-gray-600 mx-auto mb-2" />
        {file ? (
          <p className="text-sm text-gray-300">{file.name}</p>
        ) : (
          <>
            <p className="text-sm text-gray-400">
              {t('documents.dropzoneText')}{' '}
              <span className="text-blue-400">{t('documents.browse')}</span>
            </p>
            <p className="text-xs text-gray-600 mt-1">{t('v2.ingest.supported')}</p>
          </>
        )}
        <input
          ref={fileRef}
          type="file"
          accept={V2_ACCEPTED_TYPES}
          className="hidden"
          onChange={handleFileSelect}
        />
      </div>

      {/* Progress */}
      {status !== 'idle' && status !== 'failed' && (
        <div>
          <div className="flex justify-between text-xs text-gray-400 mb-1">
            <span>{phaseLabel}</span>
            <span>{progress}%</span>
          </div>
          <ProgressBar progress={progress} />
        </div>
      )}

      {/* Complete */}
      {status === 'complete' && (
        <div className="flex items-center gap-2 text-green-400 text-sm">
          <CheckCircle size={14} />
          {t('v2.ingest.phaseReady')}
        </div>
      )}

      {/* Error */}
      {status === 'failed' && (
        <div className="flex items-center gap-2 text-red-400 text-sm">
          <XCircle size={14} />
          {errorMsg || t('v2.ingest.phaseFailed')}
        </div>
      )}

      {/* Ingest button */}
      <button
        onClick={handleIngest}
        disabled={!file || isActive}
        className="w-full py-2 bg-blue-600 rounded-xl text-sm text-white font-medium hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
      >
        {isActive ? t('v2.ingest.ingesting') : t('v2.ingest.ingestBtn')}
      </button>

      {/* V2 documents list */}
      {v2Docs.length > 0 && (
        <div className="pt-2 border-t border-gray-800">
          <p className="text-xs text-gray-500 mb-2">{t('v2.ingest.docsTitle')}</p>
          <div className="space-y-1">
            {v2Docs.map(doc => (
              <div key={doc.doc_id} className="flex items-center gap-2 text-xs text-gray-400 py-1">
                <FileText size={11} className="text-blue-400 flex-shrink-0" />
                <span className="truncate flex-1">{doc.filename}</span>
                {doc.total_pages && (
                  <span className="text-gray-600 flex-shrink-0">{doc.total_pages}p</span>
                )}
                <span className="flex items-center gap-0.5 text-green-500 flex-shrink-0">
                  <CheckCircle size={10} />
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {v2Docs.length === 0 && status === 'idle' && (
        <p className="text-xs text-gray-700">{t('v2.ingest.noDocsYet')}</p>
      )}
    </div>
  )
}

// ── V1 Document Ingestion ─────────────────────────────────────────────────────
export default function DocumentIngestion() {
  const { t } = useTranslation()
  const fileRef = useRef(null)
  const pollRef = useRef(null)

  const [files, setFiles] = useState([])
  const [progress, setProgress] = useState(0)
  const [status, setStatus] = useState('idle') // idle / uploading / processing / complete / error
  const [statusMessage, setStatusMessage] = useState('')
  const [chunkCount, setChunkCount] = useState(0)
  const [jobId, setJobId] = useState(null)
  const [generateSummaries, setGenerateSummaries] = useState(true)

  // Clean up polling interval on unmount
  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current)
    }
  }, [])

  const handleFileSelect = (e) => {
    setFiles(Array.from(e.target.files))
    setStatus('idle')
    setProgress(0)
    setStatusMessage('')
    setChunkCount(0)
  }

  const handleDrop = (e) => {
    e.preventDefault()
    setFiles(Array.from(e.dataTransfer.files))
    setStatus('idle')
    setProgress(0)
    setStatusMessage('')
    setChunkCount(0)
  }

  const startPolling = (id) => {
    if (pollRef.current) clearInterval(pollRef.current)

    pollRef.current = setInterval(async () => {
      try {
        const res = await fetch(`/api/ingest/status?job_id=${id}`)
        if (!res.ok) {
          stopPolling()
          setStatus('error')
          setStatusMessage('Status check failed — see backend logs.')
          return
        }
        const data = await res.json()
        setProgress(data.progress)
        setStatusMessage(data.message)

        if (data.status === 'complete') {
          stopPolling()
          setStatus('complete')
          setChunkCount(data.chunk_count)
        } else if (data.status === 'error') {
          stopPolling()
          setStatus('error')
        }
      } catch {
        stopPolling()
        setStatus('error')
        setStatusMessage(t('common.backendError'))
      }
    }, 3000)
  }

  const stopPolling = () => {
    if (pollRef.current) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }
  }

  const handleIngest = async () => {
    if (!files.length) return

    setStatus('uploading')
    setProgress(5)
    setStatusMessage('Uploading files...')
    setChunkCount(0)

    const formData = new FormData()
    files.forEach(f => formData.append('files', f))
    formData.append('generate_summaries', generateSummaries)

    try {
      const res = await fetch('/api/ingest/docs', {
        method: 'POST',
        body: formData,
      })

      if (!res.ok) {
        const err = await res.json()
        setStatus('error')
        setStatusMessage(err.error || 'Upload failed.')
        return
      }

      const data = await res.json()
      setJobId(data.job_id)
      setStatus('processing')
      setProgress(10)
      setStatusMessage('Processing started...')
      startPolling(data.job_id)

    } catch (err) {
      setStatus('error')
      setStatusMessage(t('common.backendError'))
    }
  }

  const progressLabel = () => {
    if (status === 'complete') return `${t('documents.complete')} — ${chunkCount} ${t('documents.chunksIndexed')}`
    if (status === 'error') return t('documents.failed')
    return statusMessage || t('documents.ingesting')
  }

  const ingestButtonLabel = () => {
    if (status === 'uploading' || status === 'processing') return t('documents.ingesting')
    if (files.length > 0) {
      const count = files.length
      const word = count === 1 ? t('documents.file') : t('documents.files')
      return `${t('documents.ingestFiles').split(' ')[0]} ${count} ${word}`
    }
    return t('documents.ingestFiles')
  }

  return (
    <div className="max-w-2xl space-y-5">
      <h2 className="text-lg font-semibold text-white">{t('documents.title')}</h2>

      {/* ── V2 Smart Index section ───────────────────────────────────────── */}
      <V2IngestSection />

      {/* Drop zone */}
      <div
        onDrop={handleDrop}
        onDragOver={e => e.preventDefault()}
        onClick={() => fileRef.current?.click()}
        className="border-2 border-dashed border-gray-700 rounded-xl p-10 text-center cursor-pointer hover:border-blue-600 transition-colors"
      >
        <Upload size={28} className="text-gray-600 mx-auto mb-3" />
        <p className="text-sm text-gray-400">
          {t('documents.dropzoneText')}{' '}
          <span className="text-blue-400">{t('documents.browse')}</span>
        </p>
        <p className="text-xs text-gray-600 mt-1">{t('documents.supported')}</p>
        <input
          ref={fileRef}
          type="file"
          multiple
          accept={ACCEPTED_TYPES}
          className="hidden"
          onChange={handleFileSelect}
        />
      </div>

      {/* Selected files list */}
      {files.length > 0 && (
        <div className="space-y-2">
          {files.map((f, i) => (
            <div key={i} className="flex items-center gap-3 bg-gray-900 border border-gray-800 rounded-lg px-4 py-2.5">
              <FileText size={14} className="text-blue-400 flex-shrink-0" />
              <span className="text-sm text-gray-300 truncate">{f.name}</span>
              <span className="text-xs text-gray-600 ml-auto flex-shrink-0">
                {(f.size / 1024).toFixed(0)} KB
              </span>
            </div>
          ))}
        </div>
      )}

      {/* Progress bar */}
      {status !== 'idle' && (
        <div className="w-full">
          <div className="flex justify-between text-xs text-gray-400 mb-1">
            <span className="flex items-center gap-1">
              {/vision|image/i.test(statusMessage) && (
                <Eye size={12} className="text-blue-400 flex-shrink-0" />
              )}
              {progressLabel()}
            </span>
            <span>{progress}%</span>
          </div>
          <ProgressBar progress={progress} />
        </div>
      )}

      {/* Status messages */}
      {status === 'complete' && (
        <div className="flex items-center gap-2 text-green-400 text-sm">
          <CheckCircle size={15} />
          {t('documents.chunksSuccess', { count: chunkCount })}
        </div>
      )}
      {status === 'error' && (
        <div className="flex items-center gap-2 text-red-400 text-sm">
          <XCircle size={15} />
          {statusMessage || t('documents.failed')}
        </div>
      )}

      {/* Table summary toggle */}
      <label className="flex items-start gap-3 cursor-pointer select-none">
        <div
          onClick={() => setGenerateSummaries(v => !v)}
          className={`mt-0.5 w-9 h-5 rounded-full transition-colors flex-shrink-0 ${generateSummaries ? 'bg-blue-600' : 'bg-gray-700'} relative cursor-pointer`}
        >
          <div className={`absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform ${generateSummaries ? 'translate-x-4' : 'translate-x-0.5'}`} />
        </div>
        <div>
          <p className="text-xs text-gray-300 font-medium">Generate table summaries</p>
          <p className="text-xs text-gray-600 mt-0.5">
            {generateSummaries
              ? 'One LLM call per table chunk — slower ingest, better table retrieval'
              : 'Skipped — faster ingest, tables indexed without semantic summary'}
          </p>
        </div>
      </label>

      {/* Ingest button */}
      <button
        onClick={handleIngest}
        disabled={!files.length || status === 'uploading' || status === 'processing'}
        className="w-full py-2.5 bg-blue-600 rounded-xl text-sm text-white font-medium hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
      >
        {ingestButtonLabel()}
      </button>
    </div>
  )
}
