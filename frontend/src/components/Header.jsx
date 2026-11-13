import { Link, NavLink, useNavigate, useSearchParams } from 'react-router-dom'
import { useStore } from '../useStore'
import { CartIcon, UserIcon } from './icons'

export default function Header() {
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
        <NavLink to="/orders">Orders</NavLink>{/* guests see the orders this session placed */}
        {auth ? (
          <>
            <span className="hello">Hi, {auth.username}</span>
            <button className="link" onClick={logout}>Log out</button>
          </>
        ) : (
          <NavLink to="/login" aria-label="Log in"><UserIcon /><span className="label-wide">Log in</span></NavLink>
        )}
        <NavLink to="/cart" aria-label={`Cart, ${count} items`}>
          <CartIcon /><span className="label-wide">Cart</span>
          <span className="cart-count" data-n={count}>{count}</span>
        </NavLink>
      </nav>
    </header>
  )
}
