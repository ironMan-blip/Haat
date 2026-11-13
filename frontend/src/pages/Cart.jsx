import { Link } from 'react-router-dom'
import { EmptyState, Qty, Status, Summary } from '../components'
import { useStore } from '../store'

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
              <img src={l.thumb} alt="" width="64" height="64" />
              <div className="line-text">
                <Link to={`/p/${l.slug}`}>{l.name}</Link>
                <span className="soft">{l.price_display} each</span>
              </div>
              <Qty value={l.quantity} max={l.max_qty} onChange={(q) => setQty(l.id, q)} label={`Quantity of ${l.name}`} />
              <span className="line-total">{l.line_total_display}</span>
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
