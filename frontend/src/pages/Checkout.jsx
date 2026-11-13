import { useState } from 'react'
import { Link, Navigate, useNavigate } from 'react-router-dom'
import { api } from '../api'
import Status from '../components/Status'
import Summary from '../components/Summary'
import { useStore } from '../useStore'

export default function Checkout() {
  const { auth, cart, config, reloadCart, expire } = useStore()
  const navigate = useNavigate()
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [placed, setPlaced] = useState(false)

  if (cart && !cart.lines.length && !placed) return <Navigate to="/cart" replace />
  if (!cart || !config) return <Status loading />

  const submit = async (e) => {
    e.preventDefault()
    setBusy(true)
    setError('')
    const form = Object.fromEntries(new FormData(e.currentTarget))
    try {
      // The server builds the order from the session cart and empties it; it refuses if the
      // cart no longer matches the total shown here.
      // No token places a guest order: the server keeps it on this browser's session.
      const order = await api('/orders/', { method: 'POST', token: auth?.token, body: { ...form, expected_total: cart.total } })
      setPlaced(true) // keeps the empty-cart guard from redirecting to /cart
      reloadCart()
      navigate(`/orders?placed=${order.id}`)
    } catch (err) {
      // Stale token: never retry as a guest on their behalf, or the order silently misses their account.
      if (err.status === 401 && auth) {
        expire()
        setError('You were signed out. Log in again, or place the order as a guest.')
        return setBusy(false)
      }
      setError(err.message)
      setBusy(false)
      reloadCart() // show the cart the server has now
    }
  }

  return (
    <section className="page checkout-grid">
      <form className="form form-card" onSubmit={submit}>
        <h1>Delivery details</h1>
        {!auth && <p className="soft">Ordering as a guest. <Link to="/login?next=/checkout">Log in</Link> to track orders on any device.</p>}
        <label>Full name<input name="full_name" required maxLength={120} autoComplete="name" /></label>
        <label>Mobile number
          <input name="phone" type="tel" required placeholder="01712345678" autoComplete="tel" />
          <span className="hint">The rider will call this number before delivery.</span>
        </label>
        <label>City
          <select name="city" required defaultValue="Dhaka">
            {config.cities.map((c) => <option key={c}>{c}</option>)}
          </select>
        </label>
        <label>Address<textarea name="address" required maxLength={300} rows={3} placeholder="House, road, area" autoComplete="street-address" /></label>
        <fieldset>
          <legend>Payment</legend>
          <label className="radio"><input type="radio" defaultChecked readOnly /> Cash on delivery <span className="hint">Pay the rider when it arrives</span></label>
        </fieldset>
        {error && <p className="alert" role="alert">{error}</p>}
        <button className="btn btn--wide" disabled={busy}>{busy ? 'Placing order…' : 'Place order'}</button>
      </form>
      <Summary />
    </section>
  )
}
