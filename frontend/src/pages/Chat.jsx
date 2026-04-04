/**
 * LAKO — Chat Page (V2)
 * Session 15 (V2 Session 5): Switched to POST /api/v2/query SSE streaming.
 *   - fetch + ReadableStream SSE parser (POST body required — EventSource not usable)
 *   - RAG "Search documents" / "Search web" segmented toggle
 *   - Document selector dropdown (doc_id filter, populated from /api/v2/documents)
 *   - Timing debug panel (⚡) showing per-step ms or "cache hit" badge
 *   - Error messages styled in red (from SSE error events)
 *   - Language derived from active i18n locale (en / nl)
 * Previous sessions: typewriter streaming, stop/edit, auto-scroll, i18n.
 */

import React, { useState, useEffect, useRef, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { Send, Square, Pencil, RotateCcw, ChevronDown, Globe, FileText, ChevronRight, Zap } from 'lucide-react'
import CacheRefreshButton from '../components/CacheRefreshButton'

// ── SSE stream reader ─────────────────────────────────────────────────────────
// Parses: data: {"token":"…","done":false}  and  data: {"token":"","done":true,…}
async function readSSEStream(response, { onToken, onDone, onError }) {
  const reader  = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    // SSE events are separated by \n\n
    const parts = buffer.split('\n\n')
    buffer = parts.pop()           // keep incomplete trailing event
    for (const part of parts) {
      for (const line of part.split('\n')) {
        if (!line.startsWith('data: ')) continue
        const jsonStr = line.slice(6).trim()
        if (!jsonStr) continue
        try {
          const msg = JSON.parse(jsonStr)
          if (msg.done) {
            if (msg.error) onError(msg.error)
            else           onDone(msg.sources || [], msg.timing || null)
          } else if (typeof msg.token === 'string' && msg.token) {
            onToken(msg.token)
          }
        } catch {}
      }
    }
  }
}

// ── Timing debug panel ────────────────────────────────────────────────────────
function TimingPanel({ timing, t }) {
  if (!timing) return null
  if (timing.cache_hit) {
    return (
      <div className="mt-1.5 flex items-center gap-1.5 text-xs text-yellow-400">
        <Zap size={11} />
        {t('v2.chat.cacheHit')}
      </div>
    )
  }
  const fields = [
    ['Embed',      timing.embedding_ms],
    ['Search',     timing.search_ms],
    ['Fetch',      timing.fetch_ms],
    ['Prompt',     timing.assembly_ms],
    ['1st token',  timing.llm_first_token_ms],
    ['Total',      timing.llm_total_ms],
  ].filter(([, v]) => v != null)
  if (!fields.length) return null
  return (
    <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-gray-600">
      {fields.map(([label, ms]) => (
        <span key={label}>
          {label}: <span className="text-gray-500">{ms}ms</span>
        </span>
      ))}
    </div>
  )
}

// ── V2 source citations ───────────────────────────────────────────────────────
// RAG sources:  {doc_id, filename, page_num, score}
// Web sources:  {title, url}
function V2Citations({ sources, isWeb, t }) {
  const [expanded, setExpanded] = useState(false)
  if (!sources?.length) return null

  const label = sources.length === 1
    ? t('sources.used',       { count: 1 })
    : t('sources.usedPlural', { count: sources.length })

  return (
    <div className="mt-3 border border-gray-700 rounded-lg overflow-hidden">
      <button
        onClick={() => setExpanded(v => !v)}
        className="w-full flex items-center justify-between px-4 py-2.5 bg-gray-800 text-xs text-gray-400 hover:text-white transition-colors"
      >
        <span className="flex items-center gap-2">
          {isWeb ? <Globe size={13} /> : <FileText size={13} />}
          {label}
        </span>
        <ChevronRight
          size={13}
          className={`transition-transform duration-150 ${expanded ? 'rotate-90' : ''}`}
        />
      </button>

      {expanded && (
        <div className="divide-y divide-gray-800">
          {sources.map((src, i) => (
            <div key={i} className="px-4 py-3 bg-gray-900 text-xs">
              {isWeb ? (
                <>
                  <a
                    href={src.url}
                    target="_blank"
                    rel="noreferrer"
                    className="text-blue-400 hover:text-blue-300 transition-colors font-medium line-clamp-1"
                  >
                    {src.title || src.url}
                  </a>
                  <p className="text-gray-600 mt-0.5 truncate">{src.url}</p>
                </>
              ) : (
                <div className="flex items-center justify-between gap-3">
                  <span className="flex items-center gap-1.5 text-gray-300 font-medium truncate">
                    <FileText size={11} className="text-gray-500 flex-shrink-0" />
                    {src.filename}
                  </span>
                  <span className="text-gray-500 flex-shrink-0">
                    {t('sources.page', { page: src.page_num })} · {(src.score * 100).toFixed(0)}%
                  </span>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Typing indicator ──────────────────────────────────────────────────────────
function TypingDots() {
  return (
    <div className="flex items-center gap-1 px-1 py-2">
      {[0, 1, 2].map(i => (
        <span
          key={i}
          className="w-2 h-2 rounded-full bg-gray-500"
          style={{
            animation: 'typingBounce 1.2s ease-in-out infinite',
            animationDelay: `${i * 0.18}s`,
          }}
        />
      ))}
      <style>{`
        @keyframes typingBounce {
          0%, 60%, 100% { transform: translateY(0); opacity: 0.4; }
          30%            { transform: translateY(-6px); opacity: 1; }
        }
      `}</style>
    </div>
  )
}

// ── Message bubble ────────────────────────────────────────────────────────────
function MessageBubble({ message, isLast, streaming, onEdit, showDebug, t }) {
  const isUser = message.role === 'user'

  return (
    <div className={`flex flex-col gap-1 ${isUser ? 'items-end' : 'items-start'}`}>
      <span className="text-xs text-gray-600 px-1">{isUser ? 'You' : 'LAKO'}</span>

      <div className={`group relative max-w-[85%] ${isUser ? 'ml-12' : 'mr-12'}`}>
        <div
          className={`rounded-2xl px-4 py-3 text-sm leading-relaxed whitespace-pre-wrap break-words ${
            isUser
              ? 'bg-blue-600 text-white rounded-br-sm'
              : message.isError
              ? 'bg-red-950/60 text-red-300 border border-red-800/40 rounded-bl-sm'
              : 'bg-gray-800 text-gray-100 rounded-bl-sm'
          }`}
        >
          {message.content}
          {!isUser && isLast && streaming && (
            <span className="inline-block w-0.5 h-3.5 bg-blue-400 ml-0.5 animate-pulse align-middle rounded-full" />
          )}
        </div>

        {isUser && onEdit && !streaming && (
          <button
            onClick={() => onEdit(message)}
            className="absolute -left-8 top-1/2 -translate-y-1/2 opacity-0 group-hover:opacity-100 transition-opacity p-1.5 rounded-full text-gray-600 hover:text-gray-300 hover:bg-gray-800"
            title="Edit message"
          >
            <Pencil size={13} />
          </button>
        )}
      </div>

      {/* V2 citations + debug timing (assistant only, no error) */}
      {!isUser && !message.isError && (
        <div className="mr-12 w-full max-w-[85%]">
          <V2Citations sources={message.sources} isWeb={message.isWeb} t={t} />
          {showDebug && <TimingPanel timing={message.timing} t={t} />}
        </div>
      )}
    </div>
  )
}

// ── Main Chat component ───────────────────────────────────────────────────────
export default function Chat() {
  const { t, i18n } = useTranslation()

  const [messages,      setMessages]      = useState([])
  const [prompt,        setPrompt]        = useState('')
  const [loading,       setLoading]       = useState(false)
  const [streaming,     setStreaming]     = useState(false)
  const [ragMode,       setRagMode]       = useState('rag')   // 'rag' | 'web'
  const [selectedDocId, setSelectedDocId] = useState('')
  const [v2Docs,        setV2Docs]        = useState([])
  const [showDebug,     setShowDebug]     = useState(false)
  const [modelReady,    setModelReady]    = useState(true)
  const [showScrollBtn, setShowScrollBtn] = useState(false)

  const abortRef    = useRef(null)
  const bottomRef   = useRef(null)
  const scrollRef   = useRef(null)
  const textareaRef = useRef(null)

  // ── Fetch V2 documents for doc selector ──────────────────────────────────
  useEffect(() => {
    fetch('/api/v2/documents')
      .then(r => r.json())
      .then(d => setV2Docs(d.documents || []))
      .catch(() => setV2Docs([]))
  }, [])

  // ── Model readiness check ─────────────────────────────────────────────────
  useEffect(() => {
    let retryId
    const check = () => {
      fetch('/api/v2/ready')
        .then(r => r.json())
        .then(d => {
          setModelReady(d.ready)
          if (!d.ready) retryId = setTimeout(check, 5000)
        })
        .catch(() => setModelReady(true))   // assume ready if endpoint unreachable
    }
    check()
    return () => clearTimeout(retryId)
  }, [])

  // ── Auto-scroll ───────────────────────────────────────────────────────────
  useEffect(() => {
    if (streaming || loading) {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
    }
  }, [messages, streaming, loading])

  const handleScroll = () => {
    const el = scrollRef.current
    if (!el) return
    setShowScrollBtn(el.scrollHeight - el.scrollTop - el.clientHeight > 120)
  }

  // ── Auto-resize textarea ──────────────────────────────────────────────────
  useEffect(() => {
    const ta = textareaRef.current
    if (!ta) return
    ta.style.height = 'auto'
    ta.style.height = Math.min(ta.scrollHeight, 160) + 'px'
  }, [prompt])

  // ── Send message ──────────────────────────────────────────────────────────
  const handleSend = useCallback(async () => {
    if (!prompt.trim() || loading || streaming) return

    const userText = prompt.trim()
    const language = i18n.language.startsWith('nl') ? 'nl' : 'en'
    const isWeb    = ragMode === 'web'
    setPrompt('')
    setLoading(true)
    setStreaming(false)

    setMessages(prev => [
      ...prev,
      { role: 'user',      content: userText },
      { role: 'assistant', content: '', sources: [], timing: null, isError: false, isWeb },
    ])

    const controller = new AbortController()
    abortRef.current = controller

    try {
      const res = await fetch('/api/v2/query', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({
          query:       userText,
          language,
          rag_enabled: !isWeb,
          doc_id:      selectedDocId || null,
        }),
        signal: controller.signal,
      })

      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error(err.detail || 'Request failed')
      }

      setLoading(false)
      setStreaming(true)

      await readSSEStream(res, {
        onToken: (token) => {
          setMessages(prev => {
            const updated = [...prev]
            const last = { ...updated[updated.length - 1] }
            last.content += token
            updated[updated.length - 1] = last
            return updated
          })
        },
        onDone: (sources, timing) => {
          setMessages(prev => {
            const updated = [...prev]
            const last = { ...updated[updated.length - 1] }
            last.sources = sources
            last.timing  = timing
            updated[updated.length - 1] = last
            return updated
          })
        },
        onError: (errMsg) => {
          setMessages(prev => {
            const updated = [...prev]
            const last = { ...updated[updated.length - 1] }
            last.content = errMsg
            last.isError = true
            updated[updated.length - 1] = last
            return updated
          })
        },
      })
    } catch (err) {
      if (err.name !== 'AbortError') {
        setMessages(prev => {
          const updated = [...prev]
          const last = { ...updated[updated.length - 1] }
          last.content = last.content || err.message
          last.isError = true
          updated[updated.length - 1] = last
          return updated
        })
      }
    } finally {
      setLoading(false)
      setStreaming(false)
      abortRef.current = null
    }
  }, [prompt, loading, streaming, ragMode, selectedDocId, i18n.language])

  const handleStop = () => {
    abortRef.current?.abort()
    setLoading(false)
    setStreaming(false)
  }

  const handleEdit = (message) => {
    const idx = messages.indexOf(message)
    if (idx === -1) return
    setMessages(prev => prev.slice(0, idx))
    setPrompt(message.content)
    textareaRef.current?.focus()
  }

  const handleClear = () => {
    if (loading || streaming) handleStop()
    setMessages([])
    setPrompt('')
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const isActive       = loading || streaming
  const hasMessages    = messages.length > 0
  const noDocsInIndex  = ragMode === 'rag' && v2Docs.length === 0

  return (
    <div className="flex flex-col h-[calc(100vh-64px)] max-w-3xl w-full">

      {/* ── Models loading banner ─────────────────────────────────────────── */}
      {!modelReady && (
        <div className="shrink-0 flex items-center gap-2 text-xs text-yellow-400 bg-yellow-400/10 border border-yellow-400/20 rounded-lg px-4 py-2 mb-2">
          <span className="w-2 h-2 rounded-full bg-yellow-400 animate-pulse flex-shrink-0" />
          {t('v2.chat.modelsLoading')}
        </div>
      )}

      {/* ── No-docs warning (RAG mode, empty index) ───────────────────────── */}
      {noDocsInIndex && (
        <div className="shrink-0 text-xs text-gray-500 bg-gray-900 border border-gray-800 rounded-lg px-4 py-2 mb-2">
          {t('v2.chat.noDocsWarning')}
        </div>
      )}

      {/* ── Toolbar ──────────────────────────────────────────────────────── */}
      <div className="flex items-center gap-3 px-1 py-2 flex-wrap shrink-0">

        {/* RAG / Web segmented toggle */}
        <div className="flex rounded-lg overflow-hidden border border-gray-700 text-xs flex-shrink-0">
          <button
            onClick={() => !isActive && setRagMode('rag')}
            disabled={isActive}
            className={`px-3 py-1.5 transition-colors ${
              ragMode === 'rag'
                ? 'bg-blue-600 text-white'
                : 'bg-gray-900 text-gray-400 hover:text-gray-200'
            } disabled:opacity-50`}
          >
            {t('v2.chat.ragMode')}
          </button>
          <button
            onClick={() => !isActive && setRagMode('web')}
            disabled={isActive}
            className={`px-3 py-1.5 transition-colors ${
              ragMode === 'web'
                ? 'bg-blue-600 text-white'
                : 'bg-gray-900 text-gray-400 hover:text-gray-200'
            } disabled:opacity-50`}
          >
            {t('v2.chat.webMode')}
          </button>
        </div>

        {/* Document selector (RAG mode + docs exist) */}
        {ragMode === 'rag' && v2Docs.length > 0 && (
          <select
            value={selectedDocId}
            onChange={e => setSelectedDocId(e.target.value)}
            disabled={isActive}
            className="bg-gray-900 border border-gray-700 rounded-lg px-2 py-1 text-xs text-gray-400 focus:outline-none focus:border-blue-600 disabled:opacity-50 max-w-[180px]"
          >
            <option value="">{t('v2.chat.allDocs')}</option>
            {v2Docs.map(doc => (
              <option key={doc.doc_id} value={doc.doc_id}>{doc.filename}</option>
            ))}
          </select>
        )}

        {/* Cache refresh */}
        <CacheRefreshButton disabled={isActive} />

        {/* Debug timing toggle */}
        <button
          onClick={() => setShowDebug(v => !v)}
          className={`flex items-center gap-1 text-xs px-2 py-1 rounded-lg transition-colors ${
            showDebug
              ? 'text-yellow-400 bg-yellow-400/10 border border-yellow-400/20'
              : 'text-gray-600 hover:text-gray-400'
          }`}
          title="Toggle timing debug"
        >
          <Zap size={11} />
          {t('v2.chat.debugPanel')}
        </button>

        {hasMessages && !isActive && (
          <button
            onClick={handleClear}
            className="flex items-center gap-1 text-xs text-gray-500 hover:text-gray-300 transition-colors ml-auto"
          >
            <RotateCcw size={12} />
            {t('chat.clear')}
          </button>
        )}
      </div>

      {/* ── Message thread ───────────────────────────────────────────────── */}
      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto px-1 py-4 space-y-6 scroll-smooth"
      >
        {!hasMessages && (
          <div className="flex flex-col items-center justify-center h-full gap-3 text-center">
            <div className="w-12 h-12 rounded-2xl bg-blue-600/20 flex items-center justify-center">
              <span className="text-blue-400 text-xl font-bold">L</span>
            </div>
            <p className="text-gray-500 text-sm">{t('chat.answerPlaceholder')}</p>
          </div>
        )}

        {messages.map((msg, idx) => (
          <MessageBubble
            key={idx}
            message={msg}
            isLast={idx === messages.length - 1}
            streaming={streaming}
            onEdit={msg.role === 'user' && !isActive ? handleEdit : null}
            showDebug={showDebug}
            t={t}
          />
        ))}

        {loading && !streaming && (
          <div className="flex flex-col items-start gap-1">
            <span className="text-xs text-gray-600 px-1">LAKO</span>
            <div className="bg-gray-800 rounded-2xl rounded-bl-sm px-4 py-3">
              <TypingDots />
            </div>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* ── Scroll to bottom button ───────────────────────────────────────── */}
      {showScrollBtn && (
        <div className="flex justify-center pb-1 shrink-0">
          <button
            onClick={() => bottomRef.current?.scrollIntoView({ behavior: 'smooth' })}
            className="flex items-center gap-1.5 text-xs text-gray-400 bg-gray-800 border border-gray-700 rounded-full px-3 py-1.5 hover:bg-gray-700 transition-colors shadow-lg"
          >
            <ChevronDown size={13} />
            Scroll to bottom
          </button>
        </div>
      )}

      {/* ── Input area ───────────────────────────────────────────────────── */}
      <div className="shrink-0 pt-2 pb-1">
        <div className="relative flex items-end gap-2 bg-gray-900 border border-gray-700 rounded-2xl px-4 py-3 focus-within:border-blue-600 transition-colors">
          <textarea
            ref={textareaRef}
            value={prompt}
            onChange={e => setPrompt(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={t('chat.placeholder')}
            rows={1}
            disabled={isActive}
            className="flex-1 bg-transparent text-sm text-gray-100 placeholder-gray-600 resize-none focus:outline-none disabled:opacity-50 max-h-40 leading-relaxed"
            style={{ minHeight: '24px' }}
          />
          {isActive ? (
            <button
              onClick={handleStop}
              className="shrink-0 p-2 rounded-xl bg-red-600/20 text-red-400 hover:bg-red-600/40 transition-colors"
              title="Stop"
            >
              <Square size={15} fill="currentColor" />
            </button>
          ) : (
            <button
              onClick={handleSend}
              disabled={!prompt.trim()}
              className="shrink-0 p-2 rounded-xl bg-blue-600 text-white hover:bg-blue-500 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
              title="Send (Enter)"
            >
              <Send size={15} />
            </button>
          )}
        </div>
        <p className="text-center text-xs text-gray-700 mt-1.5">
          Enter to send · Shift+Enter for new line
        </p>
      </div>
    </div>
  )
}
