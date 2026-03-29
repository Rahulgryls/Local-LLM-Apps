/**
 * LAKO — StatCard Component
 * Reusable stat card with large value, icon, subtitle, and optional trend.
 * Session 11: Created.
 */

import React from 'react'

const COLOR_MAP = {
  blue:  { bg: 'bg-blue-500/10',  icon: 'text-blue-400',  value: 'text-blue-400'  },
  green: { bg: 'bg-green-500/10', icon: 'text-green-400', value: 'text-green-400' },
  amber: { bg: 'bg-amber-500/10', icon: 'text-amber-400', value: 'text-amber-400' },
  red:   { bg: 'bg-red-500/10',   icon: 'text-red-400',   value: 'text-red-400'   },
}

/**
 * @param {object}      props
 * @param {string}      props.title    — Label above value
 * @param {string|number} props.value  — The prominent displayed value
 * @param {string}      [props.subtitle] — Smaller text below value
 * @param {React.ReactNode} [props.icon] — Lucide icon element (size=20)
 * @param {'up'|'down'|null} [props.trend]
 * @param {'blue'|'green'|'amber'|'red'} [props.color='blue']
 */
export default function StatCard({ title, value, subtitle, icon, trend, color = 'blue' }) {
  const colors = COLOR_MAP[color] ?? COLOR_MAP.blue

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl p-5 flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <span className="text-xs text-gray-500 font-medium uppercase tracking-wide">{title}</span>
        {icon && (
          <span className={`${colors.bg} ${colors.icon} p-2 rounded-lg`}>
            {icon}
          </span>
        )}
      </div>

      <div className="flex items-end gap-2">
        <span className={`text-3xl font-bold ${colors.value}`}>{value}</span>
        {trend === 'up' && <span className="text-green-400 text-sm mb-0.5">↑</span>}
        {trend === 'down' && <span className="text-red-400 text-sm mb-0.5">↓</span>}
      </div>

      {subtitle && (
        <p className="text-xs text-gray-500 leading-snug">{subtitle}</p>
      )}
    </div>
  )
}
