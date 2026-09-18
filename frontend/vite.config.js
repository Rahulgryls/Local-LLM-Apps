import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// LAKO — Vite configuration
// Frontend dev server: http://localhost:5173
// API proxy → FastAPI backend: http://localhost:8000

export default defineConfig(({ mode }) => {
  // Deliberately NOT VITE_-prefixed: VITE_* vars get inlined into the client
  // bundle via import.meta.env. This key must stay server-side, inside this
  // Node dev-server process, never shipped to the browser. Generate it with
  // backend/scripts/bootstrap_local_key.py and put it in frontend/.env.local
  // (gitignored) as LAKO_LOCAL_API_KEY=lako_...
  const env = loadEnv(mode, process.cwd(), '')

  // Vite's dev server rejects requests whose Host header isn't recognized
  // (same DNS-rebinding-protection category as the MCP transport-security
  // fix in backend/mcp_server.py) — a tunnel (ngrok, Cloudflare) forwards the
  // original public hostname, not "localhost", so it 403s by default. Add
  // extra hostnames via LAKO_FRONTEND_ALLOWED_HOSTS (comma-separated, no
  // scheme/port) rather than hardcoding a specific tunnel domain here.
  const extraHosts = (env.LAKO_FRONTEND_ALLOWED_HOSTS || '')
    .split(',')
    .map((h) => h.trim())
    .filter(Boolean)

  return {
    plugins: [react()],
    server: {
      port: 5173,
      allowedHosts: ['localhost', '127.0.0.1', ...extraHosts],
      proxy: {
        '/api': {
          target: 'http://localhost:8000',
          changeOrigin: true,
          configure: (proxy) => {
            proxy.on('proxyReq', (proxyReq) => {
              if (env.LAKO_LOCAL_API_KEY) {
                proxyReq.setHeader('X-API-Key', env.LAKO_LOCAL_API_KEY)
              }
            })
          },
        },
      },
    },
  }
})
