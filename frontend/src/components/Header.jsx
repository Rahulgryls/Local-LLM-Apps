/**
 * LAKO — Header Component
 * Top bar with EN/NL language switcher and translated page title.
 * Session 1: Shell — Session 12: LanguageSwitcher wired, titles translated.
 */

import React from 'react'
import { useTranslation } from 'react-i18next'
import { useLocation } from 'react-router-dom'
import LanguageSwitcher from './LanguageSwitcher'

const PAGE_TITLE_KEYS = {
  '/dashboard':          'header.dashboard',
  '/chat':               'header.chat',
  '/ingest/docs':        'header.documents',
  '/ingest/confluence':  'header.confluence',
  '/vector':             'header.vector',
  '/settings':           'header.settings',
}

export default function Header() {
  const { t } = useTranslation()
  const location = useLocation()
  const titleKey = PAGE_TITLE_KEYS[location.pathname] || 'header.dashboard'

  return (
    <header className="h-14 bg-gray-900 border-b border-gray-800 flex items-center justify-between px-6">
      <h1 className="text-sm font-semibold text-gray-200">{t(titleKey)}</h1>
      <LanguageSwitcher />
    </header>
  )
}
