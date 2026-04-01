/**
 * LAKO — i18next Initialisation
 * EN (default) + NL language support.
 * Language persists in localStorage key "lako-language".
 * Detects browser language (NL) on first visit.
 * Session 12: Full translations + localStorage persistence added.
 */

import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'
import en from './en.json'
import nl from './nl.json'

// Determine initial language: localStorage > browser language > 'en'
const savedLang = localStorage.getItem('lako-language')
const browserLang = navigator.language?.slice(0, 2)
const initialLang = savedLang || (browserLang === 'nl' ? 'nl' : 'en')

i18n
  .use(initReactI18next)
  .init({
    resources: {
      en: { translation: en },
      nl: { translation: nl },
    },
    lng:         initialLang,
    fallbackLng: 'en',
    interpolation: {
      escapeValue: false,     // React already escapes
    },
  })

// Persist language choice to localStorage on every change
i18n.on('languageChanged', (lang) => {
  localStorage.setItem('lako-language', lang)
})

export default i18n
