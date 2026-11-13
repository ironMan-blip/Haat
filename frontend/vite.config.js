import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The login token lives in localStorage, so injected script must not run. Build only: the dev server
// needs inline scripts for hot reload. frame-ancestors and HSTS only work as headers: see README.
const CSP = [
  "default-src 'self'",
  "script-src 'self'",
  "style-src 'self' https://fonts.googleapis.com",
  "font-src https://fonts.gstatic.com",
  "img-src 'self' https: data:", // product photos are hotlinked from CDNs
  "connect-src 'self'",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
].join('; ')

const csp = {
  name: 'csp',
  apply: 'build',
  transformIndexHtml: () => [{ tag: 'meta', attrs: { 'http-equiv': 'Content-Security-Policy', content: CSP }, injectTo: 'head-prepend' }],
}

export default defineConfig({
  plugins: [react(), csp],
  // Keep the browser's Host header: Django's CSRF check compares it with the Origin header.
  server: { proxy: { '/api': { target: 'http://127.0.0.1:8000', changeOrigin: false } } },
})
