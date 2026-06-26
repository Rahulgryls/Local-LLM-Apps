/**
 * LAKO — Document Ingestion (unified single upload zone)
 * Pipeline toggle chooses V2 (Smart Index) or V3 (Direct RAG).
 * One drop zone, one progress bar, one document list.
 */

import React, { useState, useRef, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { Upload, FileText, CheckCircle, XCircle, Zap, Brain } from 'lucide-react'
import ProgressBar from '../components/ProgressBar'

// ── Pipeline configuration ─────────────────────────────────────────────────────

const PIPELINES = {
  v3: {
    key:         'v3',
    label:       'Direct RAG',
    description: 'Raw chunks — fast, all entities preserved. Best for large reports.',
    accepted:    '.pdf,.docx,.pptx,.xlsx,.html',
    uploadUrl:   '/api/v3/ingest',
    statusUrl:   (id) => `/api/v3/ingest/${id}/status`,
    docsUrl:     '/api/v3/documents',
    Icon:        Zap,
    badge:       'V3',
    badgeCls:    'bg-green-900/40 text-green-500',
    isDone:      (s) => s === 'indexed' || s === 'duplicate',
  },
  v2: {
    key:         'v2',
    label:       'Smart Index',
    description: 'LLM summary per page — best for short policy documents.',
    accepted:    '.pdf,.pptx,.docx',
    uploadUrl:   '/api/v2/ingest',
    statusUrl:   (id) => `/api/v2/ingest/${id}/status`,
    docsUrl:     '/api/v2/documents',
    Icon:        Brain,
    badge:       'V2',
    badgeCls:    'bg-blue-900/40 text-blue-400',
    isDone:      (s) => s === 'ready',
  },
}

// ── Phase helpers ──────────────────────────────────────────────────────────────

function getPhaseLabel(pipelineKey, data) {
  const phase = data.phase || ''
  const curr  = data.pages_processed || 0
  const tot   = data.total_pages

  if (pipelineKey === 'v3') {
    if (phase === 'parsing')
      return tot ? `Parsing — page ${curr} of ${tot}` : 'Parsing…'
    if (phase === 'embedding')
      return data.chunks_indexed
        ? `Embedding — ${data.chunks_indexed} chunks`
        : 'Embedding…'
    if (phase === 'complete' || PIPELINES.v3.isDone(data.status))
      return `Indexed — ${data.chunks_indexed || 0} chunks`
    if (phase === 'failed') return 'Failed'
    return 'Processing…'
  }

  // V2
  if (phase === 'extracting')  return 'Extracting pages…'
  if (phase === 'summarizing')
    return tot ? `Summarizing — page ${curr} of ${tot}` : 'Summarizing…'
  if (phase === 'embedding')   return 'Embedding summaries…'
  if (phase === 'complete' || PIPELINES.v2.isDone(data.status)) return 'Indexed'
  if (phase === 'failed') return 'Failed'
  return 'Processing…'
}

function getPhaseProgress(pipelineKey, data) {
  const phase = data.phase || ''
  const curr  = data.pages_processed || 0
  const tot   = data.total_pages

  if (pipelineKey === 'v3') {
    if (phase === 'parsing')
      return Math.round(5 + 75 * (tot ? curr / tot : 0))
    if (phase === 'embedding') return 85
    if (PIPELINES.v3.isDone(data.status)) return 100
    return 5
  }

  if (phase === 'extracting')  return 10
  if (phase === 'summarizing')
    return tot ? Math.round(10 + 75 * (curr / tot)) : 20
  if (phase === 'embedding')   return 90
  if (PIPELINES.v2.isDone(data.status)) return 100
  return 5
}

// ── Main component ─────────────────────────────────────────────────────────────

export default function DocumentIngestion() {
  const { t } = useTranslation()
  const fileRef = useRef(null)
  const pollRef = useRef(null)

  const [pipeline,  setPipeline]  = useState('v3')
  const [file,      setFile]      = useState(null)
  const [status,    setStatus]    = useState('idle')   // idle|uploading|processing|complete|failed
  const [pollData,  setPollData]  = useState({})
  const [errorMsg,  setErrorMsg]  = useState('')
  const [allDocs,   setAllDocs]   = useState([])

  const cfg     = PIPELINES[pipeline]
  const isActive = status === 'uploading' || status === 'processing'

  // ── Doc list ────────────────────────────────────────────────────────────────

  const fetchDocs = async () => {
    try {
      const [r2, r3] = await Promise.all([
        fetch('/api/v2/documents').then(r => r.json()).catch(() => ({ documents: [] })),
        fetch('/api/v3/documents').then(r => r.json()).catch(() => ({ documents: [] })),
      ])
      const v2Docs = (r2.documents || []).map(d => ({ ...d, _pipeline: 'v2' }))
      const v3Docs = (r3.documents || []).map(d => ({ ...d, _pipeline: 'v3' }))
      // V3 first (Direct RAG), then V2
      setAllDocs([...v3Docs, ...v2Docs])
    } catch {}
  }

  useEffect(() => {
    fetchDocs()
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, [])

  // ── Polling ─────────────────────────────────────────────────────────────────

  const stopPolling = () => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
  }

  const startPolling = (jobId, pKey) => {
    stopPolling()
    const url    = PIPELINES[pKey].statusUrl(jobId)
    const isDone = PIPELINES[pKey].isDone

    pollRef.current = setInterval(async () => {
      try {
        const res  = await fetch(url)
        const data = await res.json()
        setPollData(data)

        if (isDone(data.status)) {
          stopPolling()
          setStatus('complete')
          fetchDocs()
        } else if (data.status === 'failed') {
          stopPolling()
          setStatus('failed')
          setErrorMsg(data.error || 'Ingestion failed — check backend logs')
        }
      } catch {
        stopPolling()
        setStatus('failed')
        setErrorMsg('Connection lost — check backend')
      }
    }, 2000)
  }

  // ── File handling ────────────────────────────────────────────────────────────

  const selectFile = (f) => {
    if (!f) return
    setFile(f)
    setStatus('idle')
    setErrorMsg('')
    setPollData({})
  }

  const handleDrop = (e) => {
    e.preventDefault()
    selectFile(e.dataTransfer.files[0])
  }

  // ── Upload ───────────────────────────────────────────────────────────────────

  const handleIngest = async () => {
    if (!file) return
    setStatus('uploading')
    setPollData({})
    setErrorMsg('')

    const form = new FormData()
    form.append('file', file)

    try {
      const res = await fetch(cfg.uploadUrl, { method: 'POST', body: form })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        setStatus('failed')
        setErrorMsg(err.detail || 'Upload failed')
        return
      }
      const data = await res.json()
      setStatus('processing')
      startPolling(data.job_id, pipeline)
    } catch {
      setStatus('failed')
      setErrorMsg('Connection error — check backend')
    }
  }

  const progress = (isActive || status === 'complete')
    ? getPhaseProgress(pipeline, pollData)
    : 0

  const phaseLabel = (isActive || status === 'complete')
    ? getPhaseLabel(pipeline, pollData)
    : ''

  // ── Render ───────────────────────────────────────────────────────────────────

  return (
    <div className="max-w-2xl space-y-5">
      <h2 className="text-lg font-semibold text-white">{t('documents.title')}</h2>

      {/* Pipeline selector */}
      <div className="space-y-2">
        <div className="flex gap-2">
          {Object.values(PIPELINES).map(p => {
            const active = pipeline === p.key
            return (
              <button
                key={p.key}
                onClick={() => !isActive && setPipeline(p.key)}
                disabled={isActive}
                className={`flex items-center gap-2 px-4 py-2 rounded-xl text-sm border transition-colors
                  ${active
                    ? 'bg-blue-600 border-blue-500 text-white'
                    : 'bg-transparent border-gray-700 text-gray-400 hover:border-gray-500 hover:text-gray-300'}
                  disabled:opacity-40 disabled:cursor-not-allowed`}
              >
                <p.Icon size={13} />
                {p.label}
              </button>
            )
          })}
        </div>
        <p className="text-xs text-gray-500">{cfg.description}</p>
      </div>

      {/* Drop zone */}
      <div
        onDrop={handleDrop}
        onDragOver={e => e.preventDefault()}
        onClick={() => !isActive && fileRef.current?.click()}
        className={`border-2 border-dashed rounded-xl p-10 text-center transition-colors
          ${isActive
            ? 'border-gray-800 cursor-not-allowed opacity-50'
            : 'border-gray-700 cursor-pointer hover:border-blue-600'}`}
      >
        <Upload size={26} className="text-gray-600 mx-auto mb-3" />
        {file ? (
          <p className="text-sm text-gray-300">{file.name}</p>
        ) : (
          <>
            <p className="text-sm text-gray-400">
              {t('documents.dropzoneText')}{' '}
              <span className="text-blue-400">{t('documents.browse')}</span>
            </p>
            <p className="text-xs text-gray-600 mt-1">
              {cfg.accepted.replace(/,/g, '  ')}
            </p>
          </>
        )}
        <input
          ref={fileRef}
          type="file"
          accept={cfg.accepted}
          className="hidden"
          onChange={e => selectFile(e.target.files[0])}
        />
      </div>

      {/* Progress */}
      {(isActive || status === 'complete') && (
        <div>
          <div className="flex justify-between text-xs text-gray-400 mb-1">
            <span>{phaseLabel}</span>
            <span>{progress}%</span>
          </div>
          <ProgressBar progress={progress} />
        </div>
      )}

      {/* Result messages */}
      {status === 'complete' && (
        <div className="flex items-center gap-2 text-green-400 text-sm">
          <CheckCircle size={14} />
          {getPhaseLabel(pipeline, pollData)}
        </div>
      )}
      {status === 'failed' && (
        <div className="flex items-center gap-2 text-red-400 text-sm">
          <XCircle size={14} />
          {errorMsg}
        </div>
      )}

      {/* Upload button */}
      <button
        onClick={handleIngest}
        disabled={!file || isActive}
        className="w-full py-2.5 bg-blue-600 rounded-xl text-sm text-white font-medium
          hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
      >
        {isActive ? 'Indexing…' : 'Index document'}
      </button>

      {/* Combined document list */}
      {allDocs.length > 0 && (
        <div className="pt-3 border-t border-gray-800">
          <p className="text-xs text-gray-500 mb-2">Indexed documents</p>
          <div className="space-y-1">
            {allDocs.map(doc => {
              const p = PIPELINES[doc._pipeline]
              return (
                <div key={doc.doc_id}
                  className="flex items-center gap-2 text-xs text-gray-400 py-1">
                  <FileText size={11} className="text-blue-400 flex-shrink-0" />
                  <span className="truncate flex-1">{doc.filename}</span>
                  {(doc.total_pages || doc.page_count) && (
                    <span className="text-gray-600 flex-shrink-0">
                      {doc.total_pages || doc.page_count}p
                    </span>
                  )}
                  <span className={`flex-shrink-0 px-1.5 py-0.5 rounded text-xs ${p.badgeCls}`}>
                    {p.badge}
                  </span>
                  <CheckCircle size={10} className="text-green-500 flex-shrink-0" />
                </div>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}
