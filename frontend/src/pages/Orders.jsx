import { useEffect } from 'react'
import { Package } from 'lucide-react'
import { Link, useLocation } from 'react-router-dom'
import { useFetch } from '../api'
import EmptyState from '../components/EmptyState'
import { Line, Lines } from '../components/Lines'
import Page from '../components/Page'
import Status from '../components/Status'
import { Badge } from '../components/ui/badge'
import { Button } from '../components/ui/button'
import { Card } from '../components/ui/card'
import { textLink } from '../lib/styles'
import { useStore } from '../useStore'

const status = {
  pending: 'bg-warn-soft text-warn',
  delivered: 'bg-secondary text-secondary-foreground',
  cancelled: 'bg-sale-soft text-destructive',
}

export default function Orders() {
  const { auth, expire } = useStore()
  const notice = useLocation().state?.notice // the server's confirmation, handed over by checkout
  // Signed in: the account's orders. Guest: the orders this browser session placed.
  const state = useFetch('/orders/', auth?.token)

  useEffect(() => {
    if (state.error?.status === 401) expire() // stale token: refetches as a guest
  }, [state.error]) // eslint-disable-line react-hooks/exhaustive-deps -- expire is recreated every render

  return (
    <Page className="grid max-w-225 gap-5">
      <h1>Your orders</h1>
      {notice && <p className="my-2 flex items-center gap-2.5 rounded-lg bg-secondary px-4 py-3 font-medium text-secondary-foreground" role="status">{notice}</p>}
      {!auth && (
        <p className="text-muted-foreground">
          Orders placed without an account show here on this device only, until you log out or the session ends.
          {' '}<Link to="/login?next=/orders" className={textLink}>Log in</Link> to see your account's orders.
        </p>
      )}
      <Status {...state}>
        {state.data?.length === 0 && (
          <EmptyState heading="h2" icon={<Package strokeWidth={1.5} />} title="No orders yet" action={<Button asChild><Link to="/shop">Start shopping</Link></Button>}>
            When you place an order, you can track it here.
          </EmptyState>
        )}
        {state.data?.map((o) => (
          <article key={o.id}>
            <Card className="gap-3.5 rounded-2xl p-6 text-base ring-border">
              <div className="flex items-center justify-between gap-3">
                <h2 className="text-xl">{o.title}</h2>
                <Badge className={`h-auto px-3 py-1 text-small font-semibold capitalize ${status[o.status] ?? 'bg-muted text-muted-foreground'}`}>{o.status_display}</Badge>
              </div>
              <p className="text-muted-foreground">{o.meta_line}</p>
              <Lines>
                {o.items.map((it, i) => (
                  <Line key={i} thumb={it.thumb} size={52} slug={it.slug} name={it.name} details={[it.options, it.qty_line]} className="grid-cols-[52px_minmax(0,1fr)]" />
                ))}
              </Lines>
              <p className="border-t pt-3.5 font-bold">{o.total_line}</p>
            </Card>
          </article>
        ))}
      </Status>
    </Page>
  )
}
