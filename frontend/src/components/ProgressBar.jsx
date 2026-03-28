/**
 * LAKO — Progress Bar Component
 * Displays ingestion progress percentage.
 * Polled every 3 seconds from GET /api/ingest/status.
 * Session 1: Shell — wired in Session 11.
 */

import React from 'react'

export default function ProgressBar({ progress = 0, label = '' }) {
  return (
    <div className="w-full">
      {label && (
        <div className="flex justify-between text-xs text-gray-400 mb-1">
          <span>{label}</span>
          <span>{progress}%</span>
        </div>
      )}
      <div className="w-full bg-gray-800 rounded-full h-2">
        <div
          className="bg-blue-500 h-2 rounded-full transition-all duration-500"
          style={{ width: `${Math.min(progress, 100)}%` }}
        />
      </div>
    </div>
  )
}
