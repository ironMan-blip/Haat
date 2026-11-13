// Thin fetch wrapper. Vite proxies /api to Django in dev.
export async function api(path, { method = 'GET', body, token } = {}) {
  const headers = {}
  if (body) headers['Content-Type'] = 'application/json'
  if (token) headers.Authorization = `Token ${token}`
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

export const taka = (n) => `৳${Number(n).toLocaleString('en-IN')}`

// Daraz CDN serves resized copies via a filename suffix.
export const img = (url, size = 400) => `${url}_${size}x${size}q75.jpg`
