import { createContext, useContext, useEffect, useState } from 'react'
import { api } from './api'

const Store = createContext(null)
export const useStore = () => useContext(Store)

// localStorage can throw (private mode, blocked storage): never let it break the page.
const read = (k, fallback) => {
  try { return JSON.parse(localStorage.getItem(k)) ?? fallback } catch { return fallback }
}
const write = (k, v) => {
  try { v == null ? localStorage.removeItem(k) : localStorage.setItem(k, JSON.stringify(v)) } catch { /* ignore */ }
}

// The cart, its prices and totals live on the server (session); this only holds the last response.
export function StoreProvider({ children }) {
  const [auth, setAuth] = useState(() => read('haat-auth', null)) // {token, username}
  const [cart, setCart] = useState(null)
  const [config, setConfig] = useState(null)
  const [notice, setNotice] = useState(null) // toast: {text, link, at}

  useEffect(() => { write('haat-auth', auth) }, [auth])
  useEffect(() => {
    api('/config/').then(setConfig).catch(() => {})
    api('/cart/').then(setCart).catch(() => {})
  }, [])
  useEffect(() => {
    if (!notice) return
    const t = setTimeout(() => setNotice(null), 3500)
    return () => clearTimeout(t)
  }, [notice])

  const say = (text, link) => setNotice({ text, link, at: Date.now() })
  const call = (path, opts) => api(path, opts).then(setCart).catch((err) => say(err.message))

  const value = {
    auth, config, cart, notice,
    count: cart?.count ?? 0,
    add: (p, quantity = 1) =>
      api('/cart/', { method: 'POST', body: { product: p.id, quantity } })
        .then((c) => { setCart(c); say(`Added to cart: ${p.name}`, true) })
        .catch((err) => say(err.message)),
    setQty: (id, quantity) => call(`/cart/${id}/`, { method: 'PATCH', body: { quantity } }),
    remove: (id) => call(`/cart/${id}/`, { method: 'DELETE' }),
    reloadCart: () => call('/cart/'),
    login: setAuth,
    logout: () => {
      // Revoke the token server side too; a failed call (already stale) still signs out locally.
      if (auth) api('/auth/logout/', { method: 'POST', token: auth.token }).catch(() => {})
      setAuth(null)
    },
  }
  return <Store.Provider value={value}>{children}</Store.Provider>
}
