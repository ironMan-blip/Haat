import { useEffect, useRef, useState } from 'react'
import { CircleAlert, LoaderCircle } from 'lucide-react'
import { Link, Navigate, useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '../api'
import EmptyState from '../components/EmptyState'
import { Button } from '../components/ui/button'
import { useStore } from '../useStore'

// Opened from the email that adds guest orders to an account; the server checks the link and the account.
export default function ClaimOrders() {
  const { auth, expire, config } = useStore()
  const t = config.text.claim
  const { pathname, search } = useLocation()
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const [error, setError] = useState(null)
  const sent = useRef(false) // StrictMode runs effects twice in dev

  useEffect(() => {
    if (!auth || sent.current) return
    sent.current = true
    api('/orders/claim/', { method: 'POST', token: auth.token, body: { token: params.get('t') } })
      .then((res) => navigate('/orders', { replace: true, state: { notice: res.notice } }))
      .catch((err) => { if (err.status === 401) { sent.current = false; expire() } else setError(err.message) })
  }, [auth]) // eslint-disable-line react-hooks/exhaustive-deps -- once per sign-in

  if (!auth) return <Navigate to={`/login?next=${encodeURIComponent(pathname + search)}`} replace />
  if (!error) return <EmptyState icon={<LoaderCircle strokeWidth={1.5} className="motion-safe:animate-spin" />} title={t.busy} />
  return (
    <EmptyState icon={<CircleAlert strokeWidth={1.5} />} title={t.failed} action={<Button asChild><Link to="/orders">{t.orders}</Link></Button>}>
      {error}
    </EmptyState>
  )
}
