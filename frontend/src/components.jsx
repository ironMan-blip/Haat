import { useEffect, useRef } from 'react'
import { Link, NavLink, useNavigate, useSearchParams } from 'react-router-dom'
import { img, taka } from './api'
import { useStore } from './store'

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

// Inline icons, 1.75 stroke, currentColor.
const svg = (d) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{d}</svg>
)
const Icon = {
  cart: svg(<><path d="M3 4h2l2.4 11.2a1 1 0 0 0 1 .8h8.9a1 1 0 0 0 1-.8L20 8H6" /><circle cx="9" cy="20" r="1.3" /><circle cx="17" cy="20" r="1.3" /></>),
  user: svg(<><circle cx="12" cy="8" r="4" /><path d="M4 21a8 8 0 0 1 16 0" /></>),
  plus: svg(<path d="M12 5v14M5 12h14" />),
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
      <nav className="bar-links" aria-label="Main">
        <NavLink to="/shop">Shop</NavLink>
        {auth ? (
          <>
            <NavLink to="/orders">Orders</NavLink>
            <span className="hello">Hi, {auth.username}</span>
            <button className="link" onClick={logout}>Log out</button>
          </>
        ) : (
          <NavLink to="/login" aria-label="Log in">{Icon.user}<span className="label-wide">Log in</span></NavLink>
        )}
        <NavLink to="/cart" aria-label={`Cart, ${count} items`}>
          {Icon.cart}<span className="label-wide">Cart</span>
          <span className="cart-count" data-n={count}>{count}</span>
        </NavLink>
      </nav>
    </header>
  )
}

// The name link stretches over the whole tile (CSS ::after); the add button sits above it.
export function Tile({ p, big }) {
  const { add } = useStore()
  const d = p.discount
  const out = p.stock === 0
  return (
    <article className={`tile${big ? ' tile--big' : ''}${out ? ' tile--out' : ''}`}>
      <span className="tile-pic">
        <img src={img(p.image, big ? 600 : 400)} alt="" loading="lazy" width="400" height="400" />
        {out ? <span className="badge badge--out">Sold out</span> : d > 0 && <span className="badge">−{d}%</span>}
      </span>
      <Link to={`/p/${p.slug}`} className="tile-name">{p.name}</Link>
      {p.reviews > 0 && <Rating p={p} />}
      <span className="tile-foot">
        <span className="tile-price">
          {taka(p.price)}
          {d > 0 && <> <s>{taka(p.original_price)}</s></>}
        </span>
        {!out && (
          <button type="button" className="tile-add" onClick={() => add(p)} aria-label={`Add ${p.name} to cart`}>
            {Icon.plus}
          </button>
        )}
      </span>
    </article>
  )
}

export function Rating({ p }) {
  return (
    <span className="rating" aria-label={`Rated ${p.rating} out of 5 by ${p.reviews.toLocaleString()} buyers`}>
      <b>{p.rating}</b> ({p.reviews.toLocaleString()})
    </span>
  )
}

// `feature` enlarges every 7th tile: for short curated rows, not for long lists people scan.
export function TileGrid({ products, feature }) {
  return (
    <Reveal className="tiles">
      {products.map((p, i) => <Tile key={p.id} p={p} big={feature && i % 7 === 0} />)}
    </Reveal>
  )
}

// The live thing: how far the cart is from free delivery.
export function DeliveryMeter() {
  const { cart } = useStore()
  if (!cart?.subtotal) return null
  const left = cart.free_delivery_left
  return (
    <div className="meter" role="status">
      <p>{left > 0 ? <>Add <strong>{taka(left)}</strong> more for free delivery.</> : <>Delivery is free on this order.</>}</p>
      <span className="meter-track"><span className="meter-fill" style={{ width: `${cart.free_delivery_progress}%` }} /></span>
    </div>
  )
}

// Cart totals beside the cart and checkout pages; children hold the page's action.
export function Summary({ children }) {
  const { cart } = useStore()
  return (
    <aside className="summary" aria-label="Order summary">
      <h2>Order summary</h2>
      <DeliveryMeter />
      <dl>
        <dt>Subtotal</dt><dd>{taka(cart.subtotal)}</dd>
        <dt>Delivery</dt><dd>{cart.delivery_fee ? taka(cart.delivery_fee) : 'Free'}</dd>
        <dt className="total">Total</dt><dd className="total">{taka(cart.total)}</dd>
      </dl>
      {children}
    </aside>
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

export function Footer() {
  const { config } = useStore()
  const stamp = config?.stamp
  return (
    <footer className="foot">
      <div className="card">
        <svg className="scallops" viewBox="0 0 1200 50" preserveAspectRatio="none" aria-hidden="true">
          <path d={'M0 50' + Array.from({ length: 12 }, (_, i) => ` A50 50 0 0 1 ${(i + 1) * 100} 50`).join('') + ' Z'} />
        </svg>
        <div className="card-left">
          <p className="card-sign">See you at the haat.</p>
          <p>Order today, pay the rider in cash when the parcel reaches your door. {config && `Spend ${taka(config.free_delivery_min)} or more and delivery is on us.`}</p>
        </div>
        <div className="card-right">
          {stamp && <img className="stamp" src={img(stamp, 200)} alt="" width="88" height="117" loading="lazy" />}
          <ul className="card-links">
            <li><Link to="/shop">Every product</Link></li>
            <li><Link to="/cart">Your cart</Link></li>
            <li><Link to="/orders">Your orders</Link></li>
          </ul>
        </div>
        <p className="imprint">Haat MVP. Product photos and listings from daraz.com.bd, for demo only.</p>
      </div>
    </footer>
  )
}

export function Skeleton({ n = 8 }) {
  return (
    <div className="tiles" aria-busy="true" aria-label="Loading">
      {Array.from({ length: n }, (_, i) => (
        <div className="skel-tile" key={i}>
          <span className="skel skel-pic" />
          <span className="skel skel-line" />
          <span className="skel skel-line short" />
        </div>
      ))}
    </div>
  )
}

export function EmptyState({ icon, title, children, action }) {
  return (
    <div className="state">
      <span className="state-icon" aria-hidden="true">{icon}</span>
      <h1>{title}</h1>
      {children && <p>{children}</p>}
      {action}
    </div>
  )
}

export function Status({ loading, error, children }) {
  if (loading) return <div className="page"><Skeleton /></div>
  if (error)
    return (
      <EmptyState icon="!" title="We couldn't load this page"
        action={<button className="btn" onClick={() => location.reload()}>Try again</button>}>
        Check your connection and try again. ({error.message})
      </EmptyState>
    )
  return children
}

export function Toast() {
  const { notice } = useStore()
  if (!notice) return null
  return (
    <div className="toast" role="status" key={notice.at}>
      <p>{notice.text}</p>
      {notice.link && <Link to="/cart">View cart</Link>}
    </div>
  )
}
