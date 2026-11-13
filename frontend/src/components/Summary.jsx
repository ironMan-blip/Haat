import { useStore } from '../useStore'

// The live thing: how far the cart is from free delivery.
function DeliveryMeter() {
  const { cart } = useStore()
  if (!cart?.subtotal) return null
  return (
    <div className="meter" role="status">
      <p>{cart.meter}</p>
      <span className="meter-track"><span className="meter-fill" style={{ width: `${cart.free_delivery_progress}%` }} /></span>
    </div>
  )
}

// Cart totals beside the cart and checkout pages; children hold the page's action.
export default function Summary({ children }) {
  const { cart } = useStore()
  return (
    <aside className="summary" aria-label="Order summary">
      <h2>Order summary</h2>
      <DeliveryMeter />
      <dl>
        <dt>Subtotal</dt><dd>{cart.subtotal_display}</dd>
        <dt>Delivery</dt><dd>{cart.delivery_display}</dd>
        <dt className="total">Total</dt><dd className="total">{cart.total_display}</dd>
      </dl>
      {children}
    </aside>
  )
}
