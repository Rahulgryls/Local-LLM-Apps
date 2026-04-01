/**
 * LAKO — Language Switcher Component
 * EN / NL pill toggle. Active language highlighted in blue.
 * Persists choice to localStorage via i18n.changeLanguage().
 * Session 12: Created.
 */

import React from 'react'
import { useTranslation } from 'react-i18next'

export default function LanguageSwitcher() {
  const { i18n } = useTranslation()
  const current = i18n.language

  const setLang = (lang) => {
    if (lang !== current) {
      i18n.changeLanguage(lang)
    }
  }

  return (
    <div className="flex items-center gap-0.5 bg-gray-800 rounded-lg p-0.5">
      {['en', 'nl'].map((lang) => (
        <button
          key={lang}
          onClick={() => setLang(lang)}
          className={`px-2.5 py-1 rounded text-xs font-medium transition-colors ${
            current === lang
              ? 'bg-blue-600 text-white'
              : 'text-gray-400 hover:text-white'
          }`}
        >
          {lang.toUpperCase()}
        </button>
      ))}
    </div>
  )
}
