import { useStore } from '../useStore'
import { Line, Lines } from './Lines'
import { Card } from './ui/card'
import { Progress } from './ui/progress'

// The live thing: how far the cart is from free delivery.
function DeliveryMeter() {
  const { cart } = useStore()
  if (!cart?.subtotal) return null
  return (
    <div className="rounded-lg bg-secondary p-3.5 text-small" role="status">
      <p className="mb-2.5">{cart.meter}</p>
      <Progress value={cart.free_delivery_progress} className="h-2 bg-background" />
    </div>
  )
}

const total = 'border-t pt-3.5 text-lead font-bold text-foreground'

// Cart totals beside the cart and checkout pages; children hold the page's action.
// `lines` lists the items too, for checkout, where the cart itself is no longer on screen.
export default function Summary({ lines, children }) {
  const { cart } = useStore()
  return (
    <aside className="md:sticky md:top-22" aria-label="Order summary">
      <Card className="gap-5 rounded-2xl p-6 text-base ring-border">
        <h2 className="text-xl">Order summary</h2>
        {lines && (
          <Lines className="max-h-72 overflow-y-auto border-b pb-5">
            {cart.lines.map((l) => (
              <Line key={l.id} thumb={l.thumb} size={48} slug={l.slug} name={l.name} details={[l.options_line, l.each_line]}
                className="grid-cols-[48px_minmax(0,1fr)_auto] gap-3 text-small">
                <span className="font-semibold">{l.line_total_display}</span>
              </Line>
            ))}
          </Lines>
        )}
        <DeliveryMeter />
        {/* no column gap: the total's divider stays one line */}
        <dl className="grid grid-cols-[1fr_auto] gap-y-2.5">
          <dt className="text-muted-foreground">Subtotal</dt><dd className="text-right font-semibold">{cart.subtotal_display}</dd>
          <dt className="text-muted-foreground">Delivery</dt><dd className="text-right font-semibold">{cart.delivery_display}</dd>
          <dt className={total}>Total</dt><dd className={`${total} text-right`}>{cart.total_display}</dd>
        </dl>
        {children}
      </Card>
    </aside>
  )
}
