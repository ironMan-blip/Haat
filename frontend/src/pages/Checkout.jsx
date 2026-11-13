import { useState } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { api } from '../api'
import { useStore } from '../store'
import { Summary } from './Cart'

// Server enforces this list too (Order.CITIES in backend/shop/models.py).
const CITIES = ['Dhaka', 'Chattogram', 'Sylhet', 'Khulna', 'Rajshahi', 'Barishal', 'Rangpur', 'Mymensingh']

export default function Checkout() {
  const { auth, cart, clear } = useStore()
  const navigate = useNavigate()
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [placed, setPlaced] = useState(false)

  if (!auth) return <Navigate to="/login?next=/checkout" replace />
  if (!cart.length && !placed) return <Navigate to="/cart" replace />

  const submit = async (e) => {
    e.preventDefault()
    setBusy(true)
    setError('')
    const form = Object.fromEntries(new FormData(e.currentTarget))
    try {
      const order = await api('/orders/', {
        method: 'POST',
        token: auth.token,
        body: { ...form, lines: cart.map((l) => ({ product: l.id, quantity: l.qty })) },
      })
      setPlaced(true) // keeps the empty-cart guard from redirecting to /cart
      clear()
      navigate(`/orders?placed=${order.id}`)
    } catch (err) {
      setError(err.message)
      setBusy(false)
    }
  }

  return (
    <section className="page checkout-grid">
      <form className="form" onSubmit={submit}>
        <h1>Delivery details</h1>
        <label>Full name<input name="full_name" required maxLength={120} autoComplete="name" /></label>
        <label>Mobile number<input name="phone" required inputMode="tel" placeholder="01XXXXXXXXX" autoComplete="tel" /></label>
        <label>City
          <select name="city" required defaultValue="Dhaka">
            {CITIES.map((c) => <option key={c}>{c}</option>)}
          </select>
        </label>
        <label>Address<textarea name="address" required maxLength={300} rows={3} placeholder="House, road, area" autoComplete="street-address" /></label>
        <fieldset>
          <legend>Payment</legend>
          <label className="radio"><input type="radio" defaultChecked readOnly /> Cash on delivery</label>
        </fieldset>
        {error && <p className="error" role="alert">{error}</p>}
        <button className="btn btn--wide" disabled={busy}>{busy ? 'Placing order…' : 'Place order'}</button>
      </form>
      <Summary />
    </section>
  )
}
