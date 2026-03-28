/**
 * LAKO — Chat Page
 * Single-session stateless chat interface.
 * RAG toggle on/off, model selector, streaming response, source citations.
 * Session 1: Shell — full implementation in Session 8.
 */

import React, { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Send, Loader } from 'lucide-react'
import SourceCitations from '../components/SourceCitations'
import useAppStore from '../store/appStore'

export default function Chat() {
  const { t } = useTranslation()
  const { primaryModel } = useAppStore()
  const [prompt, setPrompt] = useState('')
  const [answer, setAnswer] = useState('')
  const [sources, setSources] = useState([])
  const [loading, setLoading] = useState(false)
  const [useRag, setUseRag] = useState(true)

  const handleSend = async () => {
    if (!prompt.trim()) return
    setLoading(true)
    setAnswer('')
    setSources([])

    try {
      // TODO (Session 8): call /api/rag/query or /api/chat with streaming
      await new Promise(r => setTimeout(r, 500))
      setAnswer('[STUB] Chat and RAG responses wired in Session 8.')
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
      <div className="flex items-center gap-4">
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

        {/* Model indicator */}
        <span className="text-xs text-gray-600">
          Model: <span className="text-blue-400 font-mono">{primaryModel || 'qwen3.5:9b'}</span>
        </span>
      </div>

      {/* Answer area */}
      <div className="min-h-40 bg-gray-900 border border-gray-800 rounded-xl p-4">
        {loading ? (
          <div className="flex items-center gap-2 text-gray-500 text-sm">
            <Loader size={14} className="animate-spin" />
            Thinking...
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
