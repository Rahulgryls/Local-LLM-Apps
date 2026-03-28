/**
 * LAKO — i18next Initialisation
 * EN (default) + NL language support.
 * Language toggle in Header component.
 * Session 1: Shell — translations expanded in Session 12.
 */

import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'
import en from './en.json'
import nl from './nl.json'

i18n
  .use(initReactI18next)
  .init({
    resources: {
      en: { translation: en },
      nl: { translation: nl },
    },
    lng:         'en',        // default language
    fallbackLng: 'en',
    interpolation: {
      escapeValue: false,     // React already escapes
    },
  })

export default i18n
