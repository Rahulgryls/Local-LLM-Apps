/**
 * LAKO — Dashboard Page
 * Real-time system stats: vector DB, models, ingestion activity.
 * Session 11: Full rewrite with live data from /api/dashboard/*.
 * Session 12: Full i18n (EN + NL).
 * Session 15 (V2 Session 5): Added V2 Index panel (Qdrant + cache + model readiness).
 */

import React, { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  RefreshCw, Database, FileText, Key, Server,
  CheckCircle, XCircle, Globe, WifiOff, AlertCircle, Zap,
} from 'lucide-react'
import StatCard from '../components/StatCard'
import useDashboard from '../hooks/useDashboard'

// ── Helpers ──────────────────────────────────────────────────────────────────

function relativeTime(isoString) {
  if (!isoString) return '—'
  const diff = Math.floor((Date.now() - new Date(isoString).getTime()) / 1000)
  if (diff < 60)  return `${diff}s`
  if (diff < 3600) return `${Math.floor(diff / 60)}m`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h`
  return `${Math.floor(diff / 86400)}d`
}

function formatDuration(seconds) {
  if (seconds == null) return '—'
  if (seconds < 60)  return `${seconds.toFixed(1)}s`
  const m = Math.floor(seconds / 60)
  const s = Math.round(seconds % 60)
  return s > 0 ? `${m}m ${s}s` : `${m}m`
}

function secondsAgo(date) {
  if (!date) return null
  return Math.floor((Date.now() - date.getTime()) / 1000)
}

// ── V2 Stats Panel ────────────────────────────────────────────────────────────

function V2StatsPanel({ refreshKey }) {
  const { t } = useTranslation()
  const [health,   setHealth]   = useState(null)
  const [ready,    setReady]    = useState(null)
  const [docCount, setDocCount] = useState(null)
  const [error,    setError]    = useState(false)

  useEffect(() => {
    Promise.all([
      fetch('/api/v2/health').then(r => r.json()),
      fetch('/api/v2/ready').then(r => r.json()),
      fetch('/api/v2/documents').then(r => r.json()),
    ])
      .then(([h, r, d]) => {
        setHealth(h)
        setReady(r)
        setDocCount(d.documents?.length ?? 0)
        setError(false)
      })
      .catch(() => setError(true))
  }, [refreshKey])

  if (error) {
    return (
      <div className="flex items-center gap-2 text-xs text-gray-600 bg-gray-900 border border-gray-800 rounded-xl px-4 py-3">
        <AlertCircle size={12} />
        {t('v2.dashboard.unavailable')}
      </div>
    )
  }

  const hitRate = health?.cache_stats?.hit_rate != null
    ? `${(health.cache_stats.hit_rate * 100).toFixed(0)}%`
    : '—'

  return (
    <div className="bg-gray-900 border border-blue-900/40 rounded-xl px-5 py-4">
      <div className="flex items-center gap-2 mb-3">
        <Zap size={13} className="text-blue-400" />
        <h3 className="text-xs font-semibold text-gray-300 uppercase tracking-wide">
          {t('v2.dashboard.title')}
        </h3>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-5 gap-4">
        {/* V2 document count */}
        <div>
          <p className="text-xs text-gray-500">{t('v2.dashboard.documents')}</p>
          <p className="text-lg font-bold text-white mt-0.5">
            {docCount !== null ? docCount.toLocaleString() : '—'}
          </p>
        </div>
        {/* Qdrant vector count */}
        <div>
          <p className="text-xs text-gray-500">{t('v2.dashboard.qdrantPoints')}</p>
          <p className="text-lg font-bold text-white mt-0.5">
            {health ? (health.points_count ?? 0).toLocaleString() : '—'}
          </p>
        </div>
        {/* Cache hit rate */}
        <div>
          <p className="text-xs text-gray-500">{t('v2.dashboard.cacheHitRate')}</p>
          <p className="text-lg font-bold text-white mt-0.5">{health ? hitRate : '—'}</p>
        </div>
        {/* LLM ready */}
        <div>
          <p className="text-xs text-gray-500">{t('v2.dashboard.llmReady')}</p>
          <div className="flex items-center gap-1.5 mt-1">
            {ready === null ? (
              <div className="w-2 h-2 rounded-full bg-gray-600 animate-pulse" />
            ) : ready?.llm ? (
              <CheckCircle size={14} className="text-green-400" />
            ) : (
              <XCircle size={14} className="text-red-400" />
            )}
            <span className="text-xs font-mono text-blue-400 truncate">
              {ready?.model_name || '—'}
            </span>
          </div>
        </div>
        {/* Embedder ready */}
        <div>
          <p className="text-xs text-gray-500">{t('v2.dashboard.embedderReady')}</p>
          <div className="flex items-center gap-1.5 mt-1">
            {ready === null ? (
              <div className="w-2 h-2 rounded-full bg-gray-600 animate-pulse" />
            ) : ready?.embedder ? (
              <CheckCircle size={14} className="text-green-400" />
            ) : (
              <XCircle size={14} className="text-red-400" />
            )}
            <span className="text-xs font-mono text-blue-400 truncate">
              {ready?.embedding_model || '—'}
            </span>
          </div>
        </div>
      </div>
    </div>
  )
}

// ── Sub-components ────────────────────────────────────────────────────────────

function ModelRow({ label, name, healthy }) {
  return (
    <div className="flex items-center justify-between py-2 border-b border-gray-800 last:border-0">
      <div>
        <p className="text-xs text-gray-500">{label}</p>
        <p className="text-sm font-mono text-blue-400 mt-0.5">{name}</p>
      </div>
      {healthy === null ? (
        <div className="w-2 h-2 rounded-full bg-gray-600 animate-pulse" />
      ) : healthy ? (
        <CheckCircle size={14} className="text-green-400 flex-shrink-0" />
      ) : (
        <XCircle size={14} className="text-red-400 flex-shrink-0" />
      )}
    </div>
  )
}

function ActivityTable({ activity, t }) {
  if (!activity || activity.length === 0) {
    return (
      <div className="text-center py-8 text-gray-600 text-sm">
        {t('dashboard.noActivity')}
      </div>
    )
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs text-gray-500 border-b border-gray-800">
            <th className="pb-2 pr-4 font-medium">{t('dashboard.colType')}</th>
            <th className="pb-2 pr-4 font-medium">{t('dashboard.colTitle')}</th>
            <th className="pb-2 pr-4 font-medium text-right">{t('dashboard.colChunks')}</th>
            <th className="pb-2 pr-4 font-medium text-right">{t('dashboard.colSize')}</th>
            <th className="pb-2 pr-4 font-medium">{t('dashboard.colStatus')}</th>
            <th className="pb-2 pr-4 font-medium text-right">{t('dashboard.colDuration')}</th>
            <th className="pb-2 font-medium text-right">{t('dashboard.colTime')}</th>
          </tr>
        </thead>
        <tbody>
          {activity.map((entry) => (
            <tr key={entry.id} className="border-b border-gray-800/60 last:border-0">
              <td className="py-2.5 pr-4">
                <div className="flex items-center gap-1">
                  {entry.type === 'confluence' ? (
                    <Globe size={13} className="text-blue-400" />
                  ) : (
                    <FileText size={13} className="text-gray-400" />
                  )}
                  {(entry.type === 'pdf' || entry.type === 'pptx') && entry.source === 'v2' && (
                    <span className="text-[9px] font-bold text-blue-400 leading-none">V2</span>
                  )}
                </div>
              </td>
              <td className="py-2.5 pr-4 max-w-xs">
                <span className="text-gray-300 truncate block" title={entry.title}>
                  {entry.title}
                </span>
              </td>
              <td className="py-2.5 pr-4 text-right text-gray-400 tabular-nums">
                {entry.chunks_indexed}
              </td>
              <td className="py-2.5 pr-4 text-right text-gray-400 text-xs tabular-nums whitespace-nowrap">
                {entry.file_size_mb != null ? `${entry.file_size_mb} MB` : '—'}
              </td>
              <td className="py-2.5 pr-4">
                {entry.status === 'success' ? (
                  <span className="inline-flex items-center gap-1 text-xs text-green-400 bg-green-400/10 px-2 py-0.5 rounded-full">
                    <CheckCircle size={10} />
                    {t('dashboard.success')}
                  </span>
                ) : entry.status === 'skipped' ? (
                  <span className="inline-flex items-center gap-1 text-xs text-yellow-400 bg-yellow-400/10 px-2 py-0.5 rounded-full">
                    <CheckCircle size={10} />
                    {t('dashboard.skipped')}
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-1 text-xs text-red-400 bg-red-400/10 px-2 py-0.5 rounded-full">
                    <XCircle size={10} />
                    {t('dashboard.failed')}
                  </span>
                )}
              </td>
              <td className="py-2.5 pr-4 text-right text-gray-400 text-xs tabular-nums whitespace-nowrap">
                {formatDuration(entry.duration_seconds)}
              </td>
              <td className="py-2.5 text-right text-gray-500 text-xs tabular-nums whitespace-nowrap">
                {relativeTime(entry.timestamp)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ── Main Component ────────────────────────────────────────────────────────────

export default function Dashboard() {
  const { t } = useTranslation()
  const { stats, activity, isLoading, error, refresh, lastUpdated } = useDashboard()
  const [secondsSince, setSecondsSince] = useState(null)

  // Tick "last updated X seconds ago" counter
  useEffect(() => {
    const id = setInterval(() => {
      setSecondsSince(secondsAgo(lastUpdated))
    }, 1000)
    return () => clearInterval(id)
  }, [lastUpdated])

  const vdb      = stats?.vector_db
  const models   = stats?.models
  const keys     = stats?.api_keys
  const ollama   = models?.ollama_status === 'healthy'

  return (
    <div className="max-w-5xl space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-white">{t('dashboard.title')}</h2>
        <div className="flex items-center gap-3">
          {lastUpdated && secondsSince !== null && (
            <span className="text-xs text-gray-600">
              {t('dashboard.updatedAgo', { count: secondsSince })}
            </span>
          )}
          <button
            onClick={refresh}
            disabled={isLoading}
            className="flex items-center gap-1.5 text-xs px-3 py-2 rounded-lg bg-gray-800 text-gray-400 hover:text-white disabled:opacity-50 transition-colors"
          >
            <RefreshCw size={12} className={isLoading ? 'animate-spin' : ''} />
            {t('dashboard.refresh')}
          </button>
        </div>
      </div>

      {/* Error banner */}
      {error && (
        <div className="flex items-center gap-2 text-xs text-red-400 bg-red-400/10 border border-red-400/20 rounded-lg px-4 py-3">
          <AlertCircle size={13} />
          {error}
        </div>
      )}

      {/* Ollama unreachable banner */}
      {stats && !ollama && (
        <div className="flex items-center gap-2 text-xs text-yellow-400 bg-yellow-400/10 border border-yellow-400/20 rounded-lg px-4 py-3">
          <WifiOff size={13} />
          {t('dashboard.ollamaUnreachable')}
        </div>
      )}

      {/* Top row — stat cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          title={t('dashboard.totalChunks')}
          value={isLoading ? '—' : (vdb?.total_chunks ?? 0).toLocaleString()}
          subtitle={`${(vdb?.sources?.pdf ?? 0)} PDF · ${(vdb?.sources?.confluence ?? 0)} Confluence`}
          icon={<Database size={16} />}
          color="blue"
        />
        <StatCard
          title={t('dashboard.documentsIndexed')}
          value={isLoading ? '—' : (vdb?.total_documents ?? 0)}
          subtitle={vdb?.last_updated
            ? t('dashboard.last', { time: relativeTime(vdb.last_updated) })
            : t('dashboard.noDocumentsYet')}
          icon={<FileText size={16} />}
          color="green"
        />
        <StatCard
          title={t('dashboard.activeApiKeys')}
          value={isLoading ? '—' : (keys?.active ?? 0)}
          subtitle={t('dashboard.total', { count: keys?.total ?? 0 })}
          icon={<Key size={16} />}
          color="amber"
        />
        <StatCard
          title={t('dashboard.ollama')}
          value={isLoading ? '—' : (ollama ? t('dashboard.online') : t('dashboard.offline'))}
          subtitle={models?.primary ?? ''}
          icon={<Server size={16} />}
          color={ollama ? 'green' : 'red'}
        />
      </div>

      {/* V2 Index panel */}
      <V2StatsPanel refreshKey={lastUpdated} />

      {/* Middle row */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">

        {/* Knowledge Base breakdown */}
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-5 space-y-4">
          <div className="flex items-center gap-2">
            <Database size={15} className="text-blue-400" />
            <h3 className="text-sm font-semibold text-white">{t('dashboard.knowledgeBase')}</h3>
          </div>
          {isLoading ? (
            <div className="space-y-2">
              {[1, 2, 3].map(i => (
                <div key={i} className="h-4 bg-gray-800 rounded animate-pulse" />
              ))}
            </div>
          ) : (
            <>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <p className="text-xs text-gray-500">{t('dashboard.pdfChunks')}</p>
                  <p className="text-xl font-bold text-white mt-0.5">
                    {(vdb?.sources?.pdf ?? 0).toLocaleString()}
                  </p>
                </div>
                <div>
                  <p className="text-xs text-gray-500">{t('dashboard.confluenceChunks')}</p>
                  <p className="text-xl font-bold text-white mt-0.5">
                    {(vdb?.sources?.confluence ?? 0).toLocaleString()}
                  </p>
                </div>
              </div>

              {/* Source ratio bar */}
              {(vdb?.total_chunks ?? 0) > 0 && (
                <div>
                  <div className="h-2 rounded-full bg-gray-800 overflow-hidden flex">
                    <div
                      className="bg-blue-500 h-full transition-all duration-500"
                      style={{ width: `${((vdb.sources.pdf / vdb.total_chunks) * 100).toFixed(1)}%` }}
                    />
                    <div
                      className="bg-cyan-500 h-full transition-all duration-500"
                      style={{ width: `${((vdb.sources.confluence / vdb.total_chunks) * 100).toFixed(1)}%` }}
                    />
                  </div>
                  <div className="flex gap-4 mt-1.5">
                    <span className="flex items-center gap-1 text-xs text-gray-500">
                      <span className="w-2 h-2 rounded-full bg-blue-500 inline-block" /> PDF
                    </span>
                    <span className="flex items-center gap-1 text-xs text-gray-500">
                      <span className="w-2 h-2 rounded-full bg-cyan-500 inline-block" /> Confluence
                    </span>
                  </div>
                </div>
              )}

              <p className="text-xs text-gray-600">
                {vdb?.last_updated
                  ? t('dashboard.lastUpdatedAt', { time: relativeTime(vdb.last_updated) })
                  : t('dashboard.noDocuments')}
              </p>
            </>
          )}
        </div>

        {/* Models status */}
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-5 space-y-1">
          <div className="flex items-center gap-2 mb-3">
            <Server size={15} className="text-blue-400" />
            <h3 className="text-sm font-semibold text-white">{t('dashboard.models')}</h3>
            {!ollama && !isLoading && (
              <span className="ml-auto text-xs text-red-400 flex items-center gap-1">
                <WifiOff size={11} /> {t('dashboard.ollamaUnreachableShort')}
              </span>
            )}
          </div>
          {isLoading ? (
            <div className="space-y-3">
              {[1, 2, 3].map(i => (
                <div key={i} className="h-10 bg-gray-800 rounded animate-pulse" />
              ))}
            </div>
          ) : (
            <>
              <ModelRow label={t('dashboard.primaryLlm')}     name={models?.primary    ?? '—'} healthy={ollama ? true : false} />
              <ModelRow label={t('dashboard.visionModel')}    name={models?.vision     ?? '—'} healthy={ollama ? true : false} />
              <ModelRow label={t('dashboard.embeddingModel')} name={models?.embeddings ?? '—'} healthy={ollama ? true : false} />
            </>
          )}
        </div>
      </div>

      {/* Recent Activity */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-semibold text-white">{t('dashboard.recentActivity')}</h3>
          {stats?.ingestion && (
            <div className="flex items-center gap-3 text-xs text-gray-500">
              <span className="text-green-400">{t('dashboard.succeeded', { count: stats.ingestion.successful })}</span>
              {stats.ingestion.skipped > 0 && (
                <span className="text-yellow-400">{t('dashboard.skippedCount', { count: stats.ingestion.skipped })}</span>
              )}
              {stats.ingestion.failed > 0 && (
                <span className="text-red-400">{t('dashboard.failedCount', { count: stats.ingestion.failed })}</span>
              )}
            </div>
          )}
        </div>
        {isLoading ? (
          <div className="space-y-3">
            {[1, 2, 3].map(i => (
              <div key={i} className="h-8 bg-gray-800 rounded animate-pulse" />
            ))}
          </div>
        ) : (
          <ActivityTable activity={activity} t={t} />
        )}
      </div>
    </div>
  )
}
