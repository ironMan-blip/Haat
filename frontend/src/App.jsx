import { useEffect } from 'react'
import { Link, Route, Routes, useLocation } from 'react-router-dom'
import { EmptyState, Footer, Header, Toast } from './components'
import Home from './pages/Home'
import Shop from './pages/Shop'
import Product from './pages/Product'
import Cart from './pages/Cart'
import Checkout from './pages/Checkout'
import Login from './pages/Login'
import Orders from './pages/Orders'

export default function App() {
  const { pathname } = useLocation()
  useEffect(() => { window.scrollTo(0, 0) }, [pathname])
  return (
    <>
      <a href="#main" className="skip">Skip to content</a>
      <Header />
      <main id="main">
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/shop" element={<Shop />} />
          <Route path="/p/:slug" element={<Product />} />
          <Route path="/cart" element={<Cart />} />
          <Route path="/checkout" element={<Checkout />} />
          <Route path="/login" element={<Login />} />
          <Route path="/orders" element={<Orders />} />
          <Route path="*" element={
            <EmptyState icon="?" title="Page not found" action={<Link to="/" className="btn">Back to the home page</Link>}>
              The link may be old or mistyped. Search above or browse the shop.
            </EmptyState>
          } />
        </Routes>
      </main>
      <Footer />
      <Toast />
    </>
  )
}
