import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// LAKO — Vite configuration
// Frontend dev server: http://localhost:5173
// API proxy → FastAPI backend: http://localhost:8000

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
