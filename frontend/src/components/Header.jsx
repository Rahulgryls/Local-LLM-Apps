/**
 * LAKO — Header Component
 * Top bar with language toggle (EN/NL) and page title.
 * Session 1: Shell — language toggle wired in Session 12.
 */

import React from 'react'
import { useTranslation } from 'react-i18next'
import { useLocation } from 'react-router-dom'

const PAGE_TITLES = {
  '/dashboard':           'Dashboard',
  '/chat':                'Chat',
  '/ingest/docs':         'Document Ingestion',
  '/ingest/confluence':   'Confluence Ingestion',
  '/vector':              'Vector Database',
  '/settings':            'Settings',
}

export default function Header() {
  const { i18n } = useTranslation()
  const location = useLocation()
  const title = PAGE_TITLES[location.pathname] || 'LAKO'

  const toggleLanguage = () => {
    const next = i18n.language === 'en' ? 'nl' : 'en'
    i18n.changeLanguage(next)
  }

  return (
    <header className="h-14 bg-gray-900 border-b border-gray-800 flex items-center justify-between px-6">
      <h1 className="text-sm font-semibold text-gray-200">{title}</h1>
      <button
        onClick={toggleLanguage}
        className="text-xs px-3 py-1.5 rounded bg-gray-800 text-gray-400 hover:text-white hover:bg-gray-700 transition-colors"
      >
        {i18n.language === 'en' ? 'NL' : 'EN'}
      </button>
    </header>
  )
}
