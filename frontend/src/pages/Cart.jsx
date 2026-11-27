import { ShoppingCart } from 'lucide-react'
import { Link } from 'react-router-dom'
import EmptyState from '../components/EmptyState'
import { Line, Lines } from '../components/Lines'
import Page from '../components/Page'
import Qty from '../components/Qty'
import Status from '../components/Status'
import Summary from '../components/Summary'
import { Button } from '../components/ui/button'
import { checkoutGrid, checkoutHead, textLink } from '../lib/styles'
import { useStore } from '../useStore'


export default function Cart() {
  const { cart, config, setQty, remove } = useStore()
  if (!cart) return <Status loading />
  if (!cart.lines.length)
    return (
      <EmptyState icon={<ShoppingCart strokeWidth={1.5} />} title="Your cart is empty" action={<Button asChild><Link to="/shop">Start shopping</Link></Button>}>
        Add something you like and it will wait for you here.
      </EmptyState>
    )
  return (
    <Page className={checkoutGrid}>
      <div>
        <h1 className={checkoutHead}>Your cart</h1>
        <Lines>
          {cart.lines.map((l) => (
            <Line key={l.id} thumb={l.thumb} size={64} slug={l.slug} name={l.name} details={[l.options_line, l.each_line]}
              className="grid-cols-[56px_minmax(0,1fr)_auto] gap-3 rounded-xl border bg-background p-3.5 md:grid-cols-[72px_minmax(0,1fr)_auto_auto_auto] md:gap-5">
              <Qty value={l.quantity} max={l.max_qty} onChange={(q) => setQty(l.id, q)} label={`Quantity of ${l.name}`}
                className="col-start-2 justify-self-start md:col-auto" />
              <span className="col-start-3 row-start-1 min-w-20 text-right font-bold md:col-auto md:row-auto">{l.line_total_display}</span>
              <Button variant="link" size="inline" className="col-start-3 row-start-2 justify-self-end text-muted-foreground hover:text-destructive md:col-auto md:row-auto"
                onClick={() => remove(l.id)} aria-label={`Remove ${l.name}`}>Remove</Button>
            </Line>
          ))}
        </Lines>
        <p className="mt-5"><Link to="/shop" className={textLink}>← Continue shopping</Link></p>
      </div>
      <Summary>
        <Button asChild className="w-full"><Link to="/checkout">Go to checkout</Link></Button>
        {config?.cart_note && <p className="text-center text-small text-muted-foreground">{config.cart_note}</p>}
      </Summary>
    </Page>
  )
}
