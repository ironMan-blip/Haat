import { ShoppingCart, User } from 'lucide-react'
import { Link, NavLink, useNavigate, useSearchParams } from 'react-router-dom'
import { cn } from 'cn'
import { useStore } from '../useStore'
import { Button } from './ui/button'
import { Input } from './ui/input'

const nav = 'inline-flex h-11 items-center gap-1.5 rounded-lg px-2.5 font-medium text-foreground no-underline transition-colors hover:bg-muted md:px-3 [&_svg]:size-5.5 [&_svg]:flex-none'
const navLink = ({ isActive }) => cn(nav, isActive && 'bg-secondary text-primary')

export default function Header() {
  const { cart, count, auth, logout, config } = useStore()
  const t = config.text.header
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const search = (e) => {
    e.preventDefault()
    const q = new FormData(e.currentTarget).get('q').trim()
    navigate(q ? `/shop?q=${encodeURIComponent(q)}` : '/shop')
  }
  return (
    <header className="sticky top-0 z-20 border-b bg-background/90 backdrop-blur-md backdrop-saturate-150">
      <div className="mx-auto flex max-w-site flex-wrap items-center gap-x-[clamp(12px,2vw,28px)] gap-y-2.5 px-gutter py-3 md:flex-nowrap">
        <Link to="/" className="inline-flex items-center gap-2 text-2xl font-bold tracking-[-0.03em] no-underline before:grid before:size-8 before:place-items-center before:rounded-lg before:bg-primary before:text-lg before:text-primary-foreground before:content-['H']">{t.brand}</Link>
        <form className="order-3 flex flex-1 basis-full md:order-none md:max-w-155 md:basis-auto" role="search" onSubmit={search}>
          <label htmlFor="q" className="sr-only">{t.search_label}</label>
          <Input id="q" name="q" type="search" placeholder={t.search_placeholder} defaultValue={params.get('q') || ''} key={params.get('q')}
            className="h-11 rounded-r-none border-r-0 border-border bg-page focus-visible:bg-background focus-visible:ring-0" />
          <Button className="h-11 rounded-l-none">{t.search}</Button>
        </form>
        <nav className="ml-auto flex items-center whitespace-nowrap md:gap-1" aria-label={t.nav_label}>
          <NavLink to="/shop" className={navLink}>{t.shop}</NavLink>
          <NavLink to="/orders" className={navLink}>{t.orders}</NavLink>{/* guests see the orders this session placed */}
          {auth ? (
            <>
              <span className="hidden pl-2 text-small text-muted-foreground md:inline">{auth.greeting}</span>
              <button className={nav} onClick={logout}>{t.logout}</button>
            </>
          ) : (
            <NavLink to="/login" aria-label={t.login} className={navLink}><User aria-hidden="true" strokeWidth={1.75} /><span className="hidden lg:inline">{t.login}</span></NavLink>
          )}
          <NavLink to="/cart" aria-label={cart?.count_label ?? t.cart} className={navLink}>
            <ShoppingCart aria-hidden="true" strokeWidth={1.75} /><span className="hidden lg:inline">{t.cart}</span>
            <span className={cn('inline-grid h-5.5 min-w-5.5 place-items-center rounded-full px-1.5 text-xs font-bold',
              count ? 'bg-primary text-primary-foreground' : 'bg-border text-muted-foreground')}>{count}</span>
          </NavLink>
        </nav>
      </div>
    </header>
  )
}
