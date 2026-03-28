/**
 * LAKO — Root App Component
 * Defines sidebar layout + page routing.
 * Session 1: Shell — full pages built in Session 2.
 */

import React from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'
import Sidebar from './components/Sidebar'
import Header from './components/Header'
import Dashboard from './pages/Dashboard'
import Chat from './pages/Chat'
import DocumentIngestion from './pages/DocumentIngestion'
import ConfluenceIngestion from './pages/ConfluenceIngestion'
import VectorDB from './pages/VectorDB'
import Settings from './pages/Settings'

export default function App() {
  return (
    <div className="flex h-screen overflow-hidden bg-gray-950">
      {/* Left sidebar navigation */}
      <Sidebar />

      {/* Main content area */}
      <div className="flex flex-col flex-1 overflow-hidden">
        <Header />
        <main className="flex-1 overflow-y-auto p-6">
          <Routes>
            <Route path="/"              element={<Navigate to="/dashboard" replace />} />
            <Route path="/dashboard"     element={<Dashboard />} />
            <Route path="/chat"          element={<Chat />} />
            <Route path="/ingest/docs"   element={<DocumentIngestion />} />
            <Route path="/ingest/confluence" element={<ConfluenceIngestion />} />
            <Route path="/vector"        element={<VectorDB />} />
            <Route path="/settings"      element={<Settings />} />
          </Routes>
        </main>
      </div>
    </div>
  )
}
