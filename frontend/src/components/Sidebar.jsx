/**
 * LAKO — Sidebar Navigation Component
 * Links to all pages. Active state highlights current route.
 * Session 1: Shell — full styling in Session 2.
 */

import React from 'react'
import { NavLink } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import {
  LayoutDashboard,
  MessageSquare,
  FileUp,
  Globe,
  Database,
  Settings,
} from 'lucide-react'

const navItems = [
  { path: '/dashboard',          icon: LayoutDashboard, labelKey: 'nav.dashboard' },
  { path: '/chat',               icon: MessageSquare,   labelKey: 'nav.chat' },
  { path: '/ingest/docs',        icon: FileUp,          labelKey: 'nav.ingestDocs' },
  { path: '/ingest/confluence',  icon: Globe,           labelKey: 'nav.ingestConfluence' },
  { path: '/vector',             icon: Database,        labelKey: 'nav.vectorDb' },
  { path: '/settings',           icon: Settings,        labelKey: 'nav.settings' },
]

export default function Sidebar() {
  const { t } = useTranslation()

  return (
    <aside className="w-56 bg-gray-900 border-r border-gray-800 flex flex-col">
      {/* Logo */}
      <div className="px-4 py-5 border-b border-gray-800">
        <span className="text-xl font-bold text-white tracking-wide">LAKO</span>
        <p className="text-xs text-gray-500 mt-0.5">Local AI Knowledge</p>
      </div>

      {/* Navigation links */}
      <nav className="flex-1 py-4 space-y-1 px-2">
        {navItems.map(({ path, icon: Icon, labelKey }) => (
          <NavLink
            key={path}
            to={path}
            className={({ isActive }) =>
              `flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-colors ${
                isActive
                  ? 'bg-blue-600 text-white'
                  : 'text-gray-400 hover:bg-gray-800 hover:text-white'
              }`
            }
          >
            <Icon size={17} />
            {t(labelKey)}
          </NavLink>
        ))}
      </nav>

      {/* Version footer */}
      <div className="px-4 py-3 border-t border-gray-800">
        <span className="text-xs text-gray-600">LAKO v1.0.0</span>
      </div>
    </aside>
  )
}
