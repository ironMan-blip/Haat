import { useEffect } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { useFetch } from '../api'
import EmptyState from '../components/EmptyState'
import Status from '../components/Status'
import { useStore } from '../useStore'

export default function Orders() {
  const { auth, expire } = useStore()
  const notice = useLocation().state?.notice // the server's confirmation, handed over by checkout
  // Signed in: the account's orders. Guest: the orders this browser session placed.
  const state = useFetch('/orders/', auth?.token)

  useEffect(() => {
    if (state.error?.status === 401) expire() // stale token: refetches as a guest
  }, [state.error]) // eslint-disable-line react-hooks/exhaustive-deps -- expire is recreated every render

  return (
    <section className="page orders">
      <h1>Your orders</h1>
      {notice && <p className="ok" role="status">{notice}</p>}
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
              <h2>{o.title}</h2>
              <span className={`status status--${o.status}`}>{o.status_display}</span>
            </div>
            <p className="soft">{o.meta_line}</p>
            <ul className="lines">
              {o.items.map((it) => (
                <li key={it.slug} className="line line--small">
                  <img src={it.thumb} alt="" width="52" height="52" loading="lazy" />
                  <div className="line-text"><Link to={`/p/${it.slug}`}>{it.name}</Link><span className="soft">{it.qty_line}</span></div>
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
