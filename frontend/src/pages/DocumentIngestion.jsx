/**
 * LAKO — Document Ingestion Page
 * File upload UI for PDF, DOCX, XLSX, PPTX, TXT.
 * Shows ingestion progress via polling.
 * Session 1: Shell — full implementation in Sessions 5–11.
 */

import React, { useState, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { Upload, FileText, CheckCircle, XCircle } from 'lucide-react'
import ProgressBar from '../components/ProgressBar'

const ACCEPTED_TYPES = '.pdf,.txt,.xlsx,.docx,.pptx'

export default function DocumentIngestion() {
  const { t } = useTranslation()
  const fileRef = useRef(null)
  const [files, setFiles] = useState([])
  const [progress, setProgress] = useState(0)
  const [status, setStatus] = useState('idle') // idle / uploading / processing / done / error
  const [jobId, setJobId] = useState(null)

  const handleFileSelect = (e) => {
    setFiles(Array.from(e.target.files))
    setStatus('idle')
    setProgress(0)
  }

  const handleDrop = (e) => {
    e.preventDefault()
    setFiles(Array.from(e.dataTransfer.files))
  }

  const handleIngest = async () => {
    if (!files.length) return
    setStatus('uploading')
    setProgress(10)

    try {
      // TODO (Session 5): POST to /api/ingest/docs with FormData, then poll /api/ingest/status
      await new Promise(r => setTimeout(r, 800))
      setJobId('stub-job-id')
      setProgress(100)
      setStatus('done')
    } catch (err) {
      setStatus('error')
    }
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
        <p className="text-xs text-gray-600 mt-1">Supported: PDF, DOCX, XLSX, PPTX, TXT</p>
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

      {/* Progress */}
      {status !== 'idle' && (
        <ProgressBar
          progress={progress}
          label={status === 'done' ? 'Ingestion complete' : 'Processing...'}
        />
      )}

      {/* Status messages */}
      {status === 'done' && (
        <div className="flex items-center gap-2 text-green-400 text-sm">
          <CheckCircle size={15} />
          Files ingested successfully. Job ID: {jobId}
        </div>
      )}
      {status === 'error' && (
        <div className="flex items-center gap-2 text-red-400 text-sm">
          <XCircle size={15} />
          Ingestion failed. Check backend logs.
        </div>
      )}

      {/* Ingest button */}
      <button
        onClick={handleIngest}
        disabled={!files.length || status === 'uploading'}
        className="w-full py-2.5 bg-blue-600 rounded-xl text-sm text-white font-medium hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
      >
        Ingest {files.length > 0 ? `${files.length} file${files.length !== 1 ? 's' : ''}` : 'Files'}
      </button>

      <p className="text-xs text-gray-600">
        [STUB] Upload pipeline wired in Session 5. Progress polling in Session 11.
      </p>
    </div>
  )
}
