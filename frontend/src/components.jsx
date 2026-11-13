import { useEffect, useRef, useState } from 'react'
import { Link, NavLink, useNavigate, useSearchParams } from 'react-router-dom'
import { api, discount, img, taka } from './api'
import { useStore } from './store'

export function useFetch(path) {
  const [state, setState] = useState({ data: null, error: null, loading: true })
  useEffect(() => {
    if (!path) return
    let live = true
    setState((s) => ({ ...s, loading: true }))
    api(path)
      .then((data) => live && setState({ data, error: null, loading: false }))
      .catch((error) => live && setState({ data: null, error, loading: false }))
    return () => { live = false }
  }, [path])
  return state
}

// Adds .in when the element scrolls into view; CSS staggers its children. Content stays visible without JS.
// eslint-disable-next-line no-unused-vars -- Tag is used as JSX
export function Reveal({ as: Tag = 'div', className = '', children, ...rest }) {
  const ref = useRef(null)
  useEffect(() => {
    const el = ref.current
    if (!el || !('IntersectionObserver' in window)) return
    el.classList.add('reveal')
    const io = new IntersectionObserver(([e]) => {
      if (e.isIntersecting) { el.classList.add('in'); io.disconnect() }
    }, { rootMargin: '0px 0px -10% 0px' })
    io.observe(el)
    return () => io.disconnect()
  }, [])
  return <Tag ref={ref} className={className} {...rest}>{children}</Tag>
}

export function Header() {
  const { count, auth, logout } = useStore()
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const search = (e) => {
    e.preventDefault()
    const q = new FormData(e.currentTarget).get('q').trim()
    navigate(q ? `/shop?q=${encodeURIComponent(q)}` : '/shop')
  }
  return (
    <header className="bar">
      <Link to="/" className="wordmark">Haat</Link>
      <form className="search" role="search" onSubmit={search}>
        <label htmlFor="q" className="sr-only">Search products</label>
        <input id="q" name="q" type="search" placeholder="Search phones, rice, bedsheets…" defaultValue={params.get('q') || ''} key={params.get('q')} />
        <button className="btn">Search</button>
      </form>
      <nav className="bar-links">
        <NavLink to="/shop">Shop</NavLink>
        {auth ? (
          <>
            <NavLink to="/orders">Orders</NavLink>
            <button className="link" onClick={logout}>Log out {auth.username}</button>
          </>
        ) : (
          <NavLink to="/login">Log in</NavLink>
        )}
        <NavLink to="/cart" className="cart-link">Cart <span className="cart-count">{count}</span></NavLink>
      </nav>
    </header>
  )
}

export function Tile({ p, big }) {
  const d = discount(p)
  return (
    <Link to={`/p/${p.slug}`} className={big ? 'tile tile--big' : 'tile'}>
      <span className="tile-pic">
        <img src={img(p.image, big ? 600 : 400)} alt="" loading="lazy" width="400" height="400" />
      </span>
      <span className="tile-name">{p.name}</span>
      <span className="tile-price">
        {taka(p.price)}
        {d > 0 && <> <s>{taka(p.original_price)}</s> <span className="off">{d}% off</span></>}
      </span>
    </Link>
  )
}

export function TileGrid({ products }) {
  return (
    <Reveal className="tiles">
      {products.map((p, i) => <Tile key={p.id} p={p} big={i % 7 === 0} />)}
    </Reveal>
  )
}

// The live thing: how far the cart is from free delivery.
export function DeliveryMeter() {
  const { subtotal, config } = useStore()
  if (!subtotal) return null
  const left = config.free_delivery_min - subtotal
  const pct = Math.min(100, (subtotal / config.free_delivery_min) * 100)
  return (
    <div className="meter" role="status">
      <p>{left > 0 ? <>Add <strong>{taka(left)}</strong> more for free delivery.</> : <>Delivery is free on this order.</>}</p>
      <span className="meter-track"><span className="meter-fill" style={{ width: `${pct}%` }} /></span>
    </div>
  )
}

export function Qty({ value, max, onChange, label }) {
  return (
    <span className="qty" role="group" aria-label={label}>
      <button type="button" onClick={() => onChange(value - 1)} disabled={value <= 1} aria-label="One less">−</button>
      <output aria-live="polite">{value}</output>
      <button type="button" onClick={() => onChange(value + 1)} disabled={value >= max} aria-label="One more">+</button>
    </span>
  )
}

export function Footer({ stamp }) {
  return (
    <footer className="foot">
      <div className="card">
        <svg className="scallops" viewBox="0 0 1200 50" preserveAspectRatio="none" aria-hidden="true">
          <path d={'M0 50' + Array.from({ length: 12 }, (_, i) => ` A50 50 0 0 1 ${(i + 1) * 100} 50`).join('') + ' Z'} />
        </svg>
        <div className="card-left">
          <p className="card-sign">See you at the haat.</p>
          <p>Order today, pay the rider in cash when the parcel reaches your door. Spend ৳299 or more and delivery is on us.</p>
        </div>
        <div className="card-right">
          {stamp && <img className="stamp" src={img(stamp, 200)} alt="" width="88" height="117" loading="lazy" />}
          <ul className="card-links">
            <li><Link to="/shop">Every product</Link></li>
            <li><Link to="/cart">Your cart</Link></li>
            <li><Link to="/orders">Your orders</Link></li>
            <li><a href="http://127.0.0.1:8000/admin/">Seller admin</a></li>
          </ul>
        </div>
        <p className="imprint">Haat MVP. Product photos and listings from daraz.com.bd, for demo only.</p>
      </div>
    </footer>
  )
}

export function Status({ loading, error, children }) {
  if (loading) return <p className="note">Loading…</p>
  if (error) return <p className="note error">Could not load: {error.message}. Is the Django server running?</p>
  return children
}
