import { useEffect, useState } from 'react'

// Django sets this cookie on the first /api/cart/ load; the cart views reject changes without it.
const csrfToken = () => document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/)?.[1]

// Thin fetch wrapper. Vite proxies /api to Django in dev.
export async function api(path, { method = 'GET', body, token } = {}) {
  const headers = {}
  if (body) headers['Content-Type'] = 'application/json'
  if (token) headers.Authorization = `Token ${token}`
  if (method !== 'GET' && csrfToken()) headers['X-CSRFToken'] = csrfToken()
  const res = await fetch(`/api${path}`, { method, headers, body: body && JSON.stringify(body) })
  const data = await res.json().catch(() => null)
  if (!res.ok) throw Object.assign(new Error(firstError(data) || `Request failed (${res.status})`), { status: res.status })
  return data
}

// DRF errors are nested {field: [msg]} or {lines: [{product: [msg]}]}: show the first message.
function firstError(data) {
  if (data == null) return null
  if (typeof data === 'string') return data
  const values = Array.isArray(data) ? data : Object.values(data)
  for (const v of values) {
    const msg = firstError(v)
    if (msg) return msg
  }
  return null
}

// GET `path` (skipped while null) and track {data, error, loading}; stale responses are dropped.
export function useFetch(path, token) {
  const [state, setState] = useState({ data: null, error: null, loading: true })
  useEffect(() => {
    if (!path) return
    let live = true
    setState((s) => ({ ...s, loading: true }))
    api(path, { token })
      .then((data) => live && setState({ data, error: null, loading: false }))
      .catch((error) => live && setState({ data: null, error, loading: false }))
    return () => { live = false }
  }, [path, token])
  return state
}

export const taka =(n) => `৳${Number(n).toLocaleString('en-IN')}`

// Daraz CDN serves resized copies via a filename suffix; other hosts get the original.
const DARAZ = /^https:\/\/[^/]+\.(slatic\.net|daraz\.com\.bd)\//
export const img = (url, size = 400) => (DARAZ.test(url) ? `${url}_${size}x${size}q75.jpg` : url)
