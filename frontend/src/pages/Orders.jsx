import { useEffect } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useFetch } from '../api'
import EmptyState from '../components/EmptyState'
import Status from '../components/Status'
import { useStore } from '../useStore'

export default function Orders() {
  const { auth, expire } = useStore()
  const [params] = useSearchParams()
  // Signed in: the account's orders. Guest: the orders this browser session placed.
  const state = useFetch('/orders/', auth?.token)
  // Only confirm an order the server returned, so a crafted ?placed= link can't fake a success banner.
  const placed = state.data?.find((o) => String(o.id) === params.get('placed'))

  useEffect(() => {
    if (state.error?.status === 401) expire() // stale token: refetches as a guest
  }, [state.error]) // eslint-disable-line react-hooks/exhaustive-deps -- expire is recreated every render

  return (
    <section className="page orders">
      <h1>Your orders</h1>
      {placed && <p className="ok" role="status">✓ Order #{placed.id} placed. Keep cash ready for the rider.</p>}
      {!auth && (
        <p className="soft">
          Orders placed without an account show here on this device only, until you log out or the session ends.
          {' '}<Link to="/login?next=/orders">Log in</Link> to see your account's orders.
        </p>
      )}
      <Status {...state}>
        {state.data?.length === 0 && (
          <EmptyState icon="📦" title="No orders yet" action={<Link to="/shop" className="btn">Start shopping</Link>}>
            When you place an order, you can track it here.
          </EmptyState>
        )}
        {state.data?.map((o) => (
          <article key={o.id} className="order">
            <div className="order-head">
              <h2>Order #{o.id}</h2>
              <span className={`status status--${o.status}`}>{o.status_display}</span>
            </div>
            <p className="soft">
              {o.created_display} · {o.city} · {o.payment_display}
            </p>
            <ul className="lines">
              {o.items.map((it) => (
                <li key={it.slug} className="line line--small">
                  <img src={it.thumb} alt="" width="52" height="52" loading="lazy" />
                  <div className="line-text"><Link to={`/p/${it.slug}`}>{it.name}</Link><span className="soft">{it.quantity} × {it.price_display}</span></div>
                </li>
              ))}
            </ul>
            <p className="order-total">{o.total_line}</p>
          </article>
        ))}
      </Status>
    </section>
  )
}
