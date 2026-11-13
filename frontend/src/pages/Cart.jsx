import { Link } from 'react-router-dom'
import { img, taka } from '../api'
import { DeliveryMeter, Qty } from '../components'
import { useStore } from '../store'

export function Summary({ children }) {
  const { subtotal, fee } = useStore()
  return (
    <aside className="summary">
      <DeliveryMeter />
      <dl>
        <dt>Subtotal</dt><dd>{taka(subtotal)}</dd>
        <dt>Delivery</dt><dd>{fee ? taka(fee) : 'Free'}</dd>
        <dt className="total">Total</dt><dd className="total">{taka(subtotal + fee)}</dd>
      </dl>
      {children}
    </aside>
  )
}

export default function Cart() {
  const { cart, setQty, remove } = useStore()
  if (!cart.length)
    return (
      <section className="page empty">
        <h1>Your cart is empty</h1>
        <p><Link to="/shop" className="btn">Browse the haat</Link></p>
      </section>
    )
  return (
    <section className="page checkout-grid">
      <div>
        <h1>Cart</h1>
        <ul className="lines">
          {cart.map((l) => (
            <li key={l.id} className="line">
              <img src={img(l.image, 200)} alt="" width="64" height="64" />
              <div className="line-text">
                <Link to={`/p/${l.slug}`}>{l.name}</Link>
                <span className="soft">{taka(l.price)} each</span>
              </div>
              <Qty value={l.qty} max={Math.min(l.stock, 20)} onChange={(q) => setQty(l.id, q)} label={`Quantity of ${l.name}`} />
              <span className="line-total">{taka(l.price * l.qty)}</span>
              <button className="link" onClick={() => remove(l.id)}>Remove</button>
            </li>
          ))}
        </ul>
      </div>
      <Summary>
        <Link to="/checkout" className="btn btn--wide">Checkout</Link>
      </Summary>
    </section>
  )
}
