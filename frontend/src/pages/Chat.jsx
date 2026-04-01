/**
 * LAKO — Chat Page
 * Single-session stateless chat interface.
 * RAG toggle on/off, model selector, streaming response, source citations.
 * Session 8: Fully implemented.
 * Session 12: Full i18n (EN + NL).
 */

import React, { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { Send, Loader, RotateCcw } from 'lucide-react'
import SourceCitations from '../components/SourceCitations'
import useAppStore from '../store/appStore'

/**
 * Parse an NDJSON stream from a fetch Response.
 * Calls onToken(str) for each token, onSources(arr) when sources arrive,
 * onError(str) if an error line is received.
 */
async function readNDJSONStream(response, { onToken, onSources, onError }) {
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { value, done } = await reader.read()
    if (done) break

    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    // Keep last (potentially incomplete) line in buffer
    buffer = lines.pop()

    for (const line of lines) {
      if (!line.trim()) continue
      try {
        const msg = JSON.parse(line)
        if (msg.t === 'token') onToken(msg.v)
        else if (msg.t === 'sources') onSources(msg.v)
        else if (msg.t === 'error') onError(msg.v)
      } catch {
        // Ignore malformed lines
      }
    }
  }

  // Flush remaining buffer
  if (buffer.trim()) {
    try {
      const msg = JSON.parse(buffer)
      if (msg.t === 'token') onToken(msg.v)
      else if (msg.t === 'sources') onSources(msg.v)
      else if (msg.t === 'error') onError(msg.v)
    } catch {}
  }
}

export default function Chat() {
  const { t } = useTranslation()
  const { primaryModel } = useAppStore()

  const [prompt, setPrompt] = useState('')
  const [answer, setAnswer] = useState('')
  const [sources, setSources] = useState([])
  const [loading, setLoading] = useState(false)
  const [streaming, setStreaming] = useState(false)
  const [useRag, setUseRag] = useState(true)
  const [selectedModel, setSelectedModel] = useState('')
  const [availableModels, setAvailableModels] = useState([])

  // Fetch installed Ollama models on mount so the selector is always populated
  useEffect(() => {
    fetch('/api/models')
      .then(r => r.json())
      .then(data => setAvailableModels(data.models || []))
      .catch(() => {})
  }, [])

  const effectiveModel = selectedModel || undefined

  const handleClear = () => {
    setPrompt('')
    setAnswer('')
    setSources([])
  }

  const handleSend = async () => {
    if (!prompt.trim() || loading) return
    setLoading(true)
    setStreaming(false)
    setAnswer('')
    setSources([])

    try {
      // Both RAG ON and OFF use /api/rag/query with NDJSON streaming
      const res = await fetch('/api/rag/query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query: prompt,
          model: effectiveModel,
          use_rag: useRag,
        }),
      })

      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error(err.detail || err.error || 'Request failed')
      }

      setStreaming(true)

      await readNDJSONStream(res, {
        onToken: (token) => setAnswer(prev => prev + token),
        onSources: (srcs) => setSources(srcs),
        onError: (msg) => setAnswer(prev => prev || ('Error: ' + msg)),
      })

    } catch (err) {
      setAnswer('Error: ' + err.message)
    } finally {
      setLoading(false)
      setStreaming(false)
    }
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <div className="max-w-3xl flex flex-col gap-4">
      {/* Controls row */}
      <div className="flex items-center gap-4 flex-wrap">
        {/* RAG toggle */}
        <label className="flex items-center gap-2 text-xs text-gray-400 cursor-pointer select-none">
          <div
            onClick={() => setUseRag(!useRag)}
            className={`w-9 h-5 rounded-full transition-colors ${useRag ? 'bg-blue-600' : 'bg-gray-700'} relative cursor-pointer`}
          >
            <div className={`absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform ${useRag ? 'translate-x-4' : 'translate-x-0.5'}`} />
          </div>
          {useRag ? t('chat.ragOn') : t('chat.ragOff')}
        </label>

        {/* Model selector — all installed Ollama models */}
        <select
          value={selectedModel}
          onChange={e => setSelectedModel(e.target.value)}
          className="bg-gray-900 border border-gray-700 rounded-lg px-2 py-1 text-xs text-blue-400 font-mono focus:outline-none focus:border-blue-600"
        >
          <option value="">{primaryModel || 'qwen3.5:35b-a3b-coding-nvfp4'} (default)</option>
          {availableModels.map(m => (
            <option key={m.name} value={m.name}>{m.name}</option>
          ))}
        </select>

        {(answer || prompt) && (
          <button
            onClick={handleClear}
            className="flex items-center gap-1 text-xs text-gray-500 hover:text-gray-300 transition-colors ml-auto"
          >
            <RotateCcw size={12} />
            {t('chat.clear')}
          </button>
        )}
      </div>

      {/* Answer area */}
      <div className="min-h-40 bg-gray-900 border border-gray-800 rounded-xl p-4">
        {loading && !streaming ? (
          <div className="flex items-center gap-2 text-gray-500 text-sm">
            <Loader size={14} className="animate-spin" />
            {useRag ? t('chat.searching') : t('chat.thinking')}
          </div>
        ) : answer ? (
          <>
            <p className="text-gray-100 text-sm leading-relaxed whitespace-pre-wrap">
              {answer}
              {streaming && <span className="inline-block w-1.5 h-3.5 bg-blue-400 ml-0.5 animate-pulse align-middle" />}
            </p>
            <SourceCitations sources={sources} />
          </>
        ) : (
          <p className="text-gray-600 text-sm">{t('chat.answerPlaceholder')}</p>
        )}
      </div>

      {/* Input area */}
      <div className="flex gap-2">
        <textarea
          value={prompt}
          onChange={e => setPrompt(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={t('chat.placeholder')}
          rows={3}
          className="flex-1 bg-gray-900 border border-gray-700 rounded-xl px-4 py-3 text-sm text-gray-100 placeholder-gray-600 resize-none focus:outline-none focus:border-blue-600 transition-colors"
        />
        <button
          onClick={handleSend}
          disabled={loading || !prompt.trim()}
          className="px-4 py-3 bg-blue-600 rounded-xl text-white hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          <Send size={16} />
        </button>
      </div>
    </div>
  )
}
