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
    api('/cart/').then(take).catch(() => {})
  }, []) // eslint-disable-line react-hooks/exhaustive-deps -- load once; take only uses setters
  useEffect(() => {
    if (!notice) return
    const t = setTimeout(() => setNotice(null), 3500)
    return () => clearTimeout(t)
  }, [notice])

  const say = (text, link) => setNotice({ text, link, at: Date.now() })
  // The server says when it changed the cart itself (sold out, less stock, quantity cap).
  const take = (c) => { setCart(c); if (c.notice) say(c.notice); return c }
  const call = (path, opts) => api(path, opts).then(take).catch((err) => say(err.message))

  const value = {
    auth, config, cart, notice,
    count: cart?.count ?? 0,
    // Resolves true once the item is in the cart, false if the server refused it.
    add: (p, quantity = 1) =>
      api('/cart/', { method: 'POST', body: { product: p.id, quantity } })
        .then((c) => { setCart(c); say(c.notice, true); return true })
        .catch((err) => { say(err.message); return false }),
    setQty: (id, quantity) => call(`/cart/${id}/`, { method: 'PATCH', body: { quantity } }),
    remove: (id) => call(`/cart/${id}/`, { method: 'DELETE' }),
    reloadCart: () => call('/cart/'),
    login: setAuth,
    expire: () => setAuth(null), // stale token: forget it but keep the cart, they'll log back in
    logout: () => {
      // Revokes the token and empties this device's cart server side; signing out locally never waits on it.
      api('/auth/logout/', { method: 'POST', token: auth?.token }).catch(() => {}).finally(() => call('/cart/'))
      setAuth(null)
    },
  }
  return <Store.Provider value={value}>{children}</Store.Provider>
}
