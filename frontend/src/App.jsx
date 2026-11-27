import { lazy, Suspense, useEffect } from 'react'
import { FileQuestion } from 'lucide-react'
import { Link, Route, Routes, useLocation } from 'react-router-dom'
import { Button } from './components/ui/button'
import EmptyState from './components/EmptyState'
import Footer from './components/Footer'
import Header from './components/Header'
import Status from './components/Status'
import Toast from './components/Toast'
import Home from './pages/Home'
import { useStore } from './useStore'

// Home is the landing page, so it ships in the first bundle; the rest load on first visit.
const Shop = lazy(() => import('./pages/Shop'))
const Product = lazy(() => import('./pages/Product'))
const Cart = lazy(() => import('./pages/Cart'))
const Checkout = lazy(() => import('./pages/Checkout'))
const Login = lazy(() => import('./pages/Login'))
const Orders = lazy(() => import('./pages/Orders'))
const ClaimOrders = lazy(() => import('./pages/ClaimOrders'))
const Connect = lazy(() => import('./pages/Connect'))

export default function App() {
  const { pathname } = useLocation()
  const { config, configError } = useStore()
  useEffect(() => { window.scrollTo(0, 0) }, [pathname])
  // Every page's words come with the config, so nothing renders before it.
  if (!config) return <Status loading={!configError} error={configError} />
  const t = config.text
  return (
    <>
      <a href="#main" className="sr-only z-30 rounded-lg bg-foreground px-4 py-2 text-background focus:not-sr-only focus:fixed focus:top-2 focus:left-2">{t.skip_link}</a>
      <Header />
      <main id="main">
        <Suspense fallback={<Status loading />}>
          <Routes>
            <Route path="/" element={<Home />} />
            <Route path="/shop" element={<Shop />} />
            <Route path="/p/:slug" element={<Product />} />
            <Route path="/cart" element={<Cart />} />
            <Route path="/checkout" element={<Checkout />} />
            <Route path="/login" element={<Login />} />
            <Route path="/orders" element={<Orders />} />
            <Route path="/orders/claim" element={<ClaimOrders />} />
            <Route path="/connect" element={<Connect />} />
            <Route path="*" element={
              <EmptyState icon={<FileQuestion strokeWidth={1.5} />} title={t.not_found.title} action={<Button asChild><Link to="/">{t.not_found.action}</Link></Button>}>
                {t.not_found.body}
              </EmptyState>
            } />
          </Routes>
        </Suspense>
      </main>
      <Footer />
      <Toast />
    </>
  )
}
