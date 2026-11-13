import { useEffect } from 'react'
import { Link, Navigate, useSearchParams } from 'react-router-dom'
import { img, taka, useFetch } from '../api'
import { EmptyState, Status } from '../components'
import { useStore } from '../store'

export default function Orders() {
  const { auth, logout } = useStore()
  const [params] = useSearchParams()
  const state = useFetch(auth && '/orders/', auth?.token)

  useEffect(() => {
    if (state.error?.status === 401) logout() // stale token
  }, [state.error]) // eslint-disable-line react-hooks/exhaustive-deps -- logout is recreated every render

  if (!auth) return <Navigate to="/login?next=/orders" replace />

  return (
    <section className="page orders">
      <h1>Your orders</h1>
      {params.get('placed') && <p className="ok" role="status">✓ Order #{params.get('placed')} placed. Keep cash ready for the rider.</p>}
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
              {new Date(o.created).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })} · {o.city} · {o.payment_display}
            </p>
            <ul className="lines">
              {o.items.map((it) => (
                <li key={it.slug} className="line line--small">
                  <img src={img(it.image, 200)} alt="" width="52" height="52" loading="lazy" />
                  <div className="line-text"><Link to={`/p/${it.slug}`}>{it.name}</Link><span className="soft">{it.quantity} × {taka(it.price)}</span></div>
                </li>
              ))}
            </ul>
            <p className="order-total">Total {taka(o.total)} {o.delivery_fee ? `(incl. ${taka(o.delivery_fee)} delivery)` : '(free delivery)'}</p>
          </article>
        ))}
      </Status>
    </section>
  )
}
