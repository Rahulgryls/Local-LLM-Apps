/**
 * LAKO — Chat Page
 * Single-session stateless chat interface.
 * RAG toggle on/off, model selector, streaming response, source citations.
 * Session 8: Fully implemented.
 */

import React, { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Send, Loader, RotateCcw } from 'lucide-react'
import SourceCitations from '../components/SourceCitations'
import useAppStore from '../store/appStore'

export default function Chat() {
  const { t } = useTranslation()
  const { primaryModel, availableModels } = useAppStore()

  const [prompt, setPrompt] = useState('')
  const [answer, setAnswer] = useState('')
  const [sources, setSources] = useState([])
  const [loading, setLoading] = useState(false)
  const [useRag, setUseRag] = useState(true)
  const [selectedModel, setSelectedModel] = useState('')

  // Empty string → backend uses config default (primary_model)
  const effectiveModel = selectedModel || undefined

  const handleClear = () => {
    setPrompt('')
    setAnswer('')
    setSources([])
  }

  const handleSend = async () => {
    if (!prompt.trim() || loading) return
    setLoading(true)
    setAnswer('')
    setSources([])

    try {
      if (useRag) {
        // ── RAG mode: retrieve + generate, returns full JSON ──────────
        const res = await fetch('/api/rag/query', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            query: prompt,
            model: effectiveModel,
            use_rag: true,
          }),
        })
        if (!res.ok) {
          const err = await res.json().catch(() => ({}))
          throw new Error(err.detail || 'RAG query failed')
        }
        const data = await res.json()
        setAnswer(data.answer)
        setSources(data.sources || [])

      } else {
        // ── Direct streaming chat ─────────────────────────────────────
        const res = await fetch('/api/chat', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            prompt,
            model: effectiveModel,
            stream: true,
          }),
        })
        if (!res.ok) {
          const err = await res.json().catch(() => ({}))
          throw new Error(err.detail || 'Chat request failed')
        }

        const reader = res.body.getReader()
        const decoder = new TextDecoder()
        let accumulated = ''

        while (true) {
          const { value, done } = await reader.read()
          if (done) break
          accumulated += decoder.decode(value, { stream: true })
          setAnswer(accumulated)
        }
        // Flush any remaining bytes
        accumulated += decoder.decode()
        setAnswer(accumulated)
      }

    } catch (err) {
      setAnswer('Error: ' + err.message)
    } finally {
      setLoading(false)
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
          RAG {useRag ? 'ON' : 'OFF'}
        </label>

        {/* Model selector */}
        <select
          value={selectedModel}
          onChange={e => setSelectedModel(e.target.value)}
          className="bg-gray-900 border border-gray-700 rounded-lg px-2 py-1 text-xs text-blue-400 font-mono focus:outline-none focus:border-blue-600"
        >
          <option value="">{primaryModel || 'qwen3.5:9b'}</option>
          {availableModels
            .filter(m => m.name !== primaryModel)
            .map(m => (
              <option key={m.name} value={m.name}>{m.name}</option>
            ))}
        </select>

        {/* Clear button — only visible when there is content to clear */}
        {(answer || prompt) && (
          <button
            onClick={handleClear}
            className="flex items-center gap-1 text-xs text-gray-500 hover:text-gray-300 transition-colors ml-auto"
          >
            <RotateCcw size={12} />
            Clear
          </button>
        )}
      </div>

      {/* Answer area */}
      <div className="min-h-40 bg-gray-900 border border-gray-800 rounded-xl p-4">
        {loading ? (
          <div className="flex items-center gap-2 text-gray-500 text-sm">
            <Loader size={14} className="animate-spin" />
            {useRag ? 'Searching knowledge base...' : 'Thinking...'}
          </div>
        ) : answer ? (
          <>
            <p className="text-gray-100 text-sm leading-relaxed whitespace-pre-wrap">{answer}</p>
            <SourceCitations sources={sources} />
          </>
        ) : (
          <p className="text-gray-600 text-sm">Your answer will appear here.</p>
        )}
      </div>

      {/* Input area */}
      <div className="flex gap-2">
        <textarea
          value={prompt}
          onChange={e => setPrompt(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={t('chat.placeholder') || 'Ask a question about your documents...'}
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
