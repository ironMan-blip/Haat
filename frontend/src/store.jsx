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

export function StoreProvider({ children }) {
  const [auth, setAuth] = useState(() => read('haat-auth', null)) // {token, username}
  const [cart, setCart] = useState(() => read('haat-cart', []))
  const [config, setConfig] = useState({ free_delivery_min: 299, delivery_fee: 60 })
  const [notice, setNotice] = useState(null) // last added item, shown as a toast

  useEffect(() => { write('haat-cart', cart) }, [cart])
  useEffect(() => { write('haat-auth', auth) }, [auth])
  useEffect(() => { api('/config/').then(setConfig).catch(() => {}) }, [])
  useEffect(() => {
    if (!notice) return
    const t = setTimeout(() => setNotice(null), 3500)
    return () => clearTimeout(t)
  }, [notice])

  const setQty = (id, qty) =>
    setCart((c) => c.map((l) => (l.id === id ? { ...l, qty: Math.max(1, Math.min(qty, l.stock, 20)) } : l)))

  const add = (p, qty = 1) => {
    setNotice({ name: p.name, at: Date.now() })
    setCart((c) => {
      const line = c.find((l) => l.id === p.id)
      if (line) return c.map((l) => (l === line ? { ...l, qty: Math.min(l.qty + qty, p.stock, 20) } : l))
      return [...c, { id: p.id, slug: p.slug, name: p.name, price: p.price, image: p.image, stock: p.stock, qty }]
    })
  }

  const subtotal = cart.reduce((s, l) => s + l.price * l.qty, 0)
  const fee = subtotal === 0 || subtotal >= config.free_delivery_min ? 0 : config.delivery_fee

  const value = {
    auth, config, cart, subtotal, fee, notice,
    count: cart.reduce((s, l) => s + l.qty, 0),
    add, setQty,
    remove: (id) => setCart((c) => c.filter((l) => l.id !== id)),
    clear: () => setCart([]),
    login: setAuth,
    logout: () => {
      // Revoke the token server side too; a failed call (already stale) still signs out locally.
      if (auth) api('/auth/logout/', { method: 'POST', token: auth.token }).catch(() => {})
      setAuth(null)
    },
  }
  return <Store.Provider value={value}>{children}</Store.Provider>
}
