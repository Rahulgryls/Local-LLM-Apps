/**
 * LAKO — Document Ingestion Page
 * File upload UI for PDF, TXT, XLSX, DOCX, PPTX.
 * Wires to POST /api/ingest/docs, polls GET /api/ingest/status every 3s.
 * Session 5: Fully wired.
 */

import React, { useState, useRef, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { Upload, FileText, CheckCircle, XCircle, Eye } from 'lucide-react'
import ProgressBar from '../components/ProgressBar'

const ACCEPTED_TYPES = '.pdf,.txt,.xlsx,.docx,.pptx'

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
        setStatusMessage('Cannot reach backend.')
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
      setStatusMessage('Cannot reach backend. Is the server running?')
    }
  }

  const progressLabel = () => {
    if (status === 'complete') return `Ingestion complete — ${chunkCount} chunks indexed`
    if (status === 'error') return 'Ingestion failed'
    return statusMessage || 'Processing...'
  }

  return (
    <div className="max-w-2xl space-y-5">
      <h2 className="text-lg font-semibold text-white">Document Ingestion</h2>

      {/* Drop zone */}
      <div
        onDrop={handleDrop}
        onDragOver={e => e.preventDefault()}
        onClick={() => fileRef.current?.click()}
        className="border-2 border-dashed border-gray-700 rounded-xl p-10 text-center cursor-pointer hover:border-blue-600 transition-colors"
      >
        <Upload size={28} className="text-gray-600 mx-auto mb-3" />
        <p className="text-sm text-gray-400">
          Drop files here or <span className="text-blue-400">click to browse</span>
        </p>
        <p className="text-xs text-gray-600 mt-1">Supported: PDF, TXT, XLSX, DOCX, PPTX</p>
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
          {chunkCount} chunk{chunkCount !== 1 ? 's' : ''} indexed successfully.
        </div>
      )}
      {status === 'error' && (
        <div className="flex items-center gap-2 text-red-400 text-sm">
          <XCircle size={15} />
          {statusMessage || 'Ingestion failed. Check backend logs.'}
        </div>
      )}

      {/* Ingest button */}
      <button
        onClick={handleIngest}
        disabled={!files.length || status === 'uploading' || status === 'processing'}
        className="w-full py-2.5 bg-blue-600 rounded-xl text-sm text-white font-medium hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
      >
        {status === 'uploading' || status === 'processing'
          ? 'Ingesting...'
          : `Ingest ${files.length > 0 ? `${files.length} file${files.length !== 1 ? 's' : ''}` : 'Files'}`}
      </button>
    </div>
  )
}
