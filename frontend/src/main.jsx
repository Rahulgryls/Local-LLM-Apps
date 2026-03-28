/**
 * LAKO — Frontend Entry Point
 * Bootstraps React app with routing and i18n.
 * Session 1: Shell — pages wired in Sessions 2–12.
 */

import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import './index.css'
import App from './App'
import './i18n/i18n'   // initialise i18next (EN + NL)

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </React.StrictMode>
)
