import { Link } from 'react-router-dom'
import { img, taka } from '../api'
import { DeliveryMeter, EmptyState, Qty, Status } from '../components'
import { useStore } from '../store'

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

export default function Cart() {
  const { cart, setQty, remove } = useStore()
  if (!cart) return <Status loading />
  if (!cart.lines.length)
    return (
      <EmptyState icon="🛒" title="Your cart is empty" action={<Link to="/shop" className="btn">Start shopping</Link>}>
        Add something you like and it will wait for you here.
      </EmptyState>
    )
  return (
    <section className="page checkout-grid">
      <div>
        <h1>Your cart</h1>
        <ul className="lines">
          {cart.lines.map((l) => (
            <li key={l.id} className="line">
              <img src={img(l.image, 200)} alt="" width="64" height="64" />
              <div className="line-text">
                <Link to={`/p/${l.slug}`}>{l.name}</Link>
                <span className="soft">{taka(l.price)} each</span>
              </div>
              <Qty value={l.quantity} max={l.max_qty} onChange={(q) => setQty(l.id, q)} label={`Quantity of ${l.name}`} />
              <span className="line-total">{taka(l.line_total)}</span>
              <button className="link link--danger" onClick={() => remove(l.id)} aria-label={`Remove ${l.name}`}>Remove</button>
            </li>
          ))}
        </ul>
        <p className="back"><Link to="/shop" className="arrow">← Continue shopping</Link></p>
      </div>
      <Summary>
        <Link to="/checkout" className="btn btn--wide">Go to checkout</Link>
        <p className="summary-note">Pay in cash when your order arrives.</p>
      </Summary>
    </section>
  )
}
