import { useEffect, useState } from 'react'
import { CircleAlert, LoaderCircle } from 'lucide-react'
import { Link, Navigate, useLocation } from 'react-router-dom'
import { cn } from 'cn'
import { api, useFetch } from '../api'
import EmptyState from '../components/EmptyState'
import Fail from '../components/Fail'
import Page from '../components/Page'
import { Button } from '../components/ui/button'
import { formCard, hint } from '../lib/styles'
import { useStore } from '../useStore'

// An AI app (through the MCP server) asks to use the buyer's account. The query is the app's sign-in request;
// the server checks it, writes what this page says and, once answered, says where the browser goes.
export default function Connect() {
  const { auth, expire, config } = useStore()
  const t = config.text.connect
  const { pathname, search } = useLocation()
  const path = `/oauth/connect/${search}`
  const { data, error } = useFetch(auth ? path : null, auth?.token)
  const [answer, setAnswer] = useState({ busy: false, error: '' })
  const leaving = data?.redirect || answer.redirect

  useEffect(() => { if (error?.status === 401) expire() }, [error]) // eslint-disable-line react-hooks/exhaustive-deps
  // The app's own return address (the server refuses any it didn't register), so leave the site for it.
  useEffect(() => { if (leaving) window.location.assign(leaving) }, [leaving])

  const send = async (allow) => {
    setAnswer({ busy: true, error: '' })
    try {
      const res = await api(path, { method: 'POST', token: auth.token, body: { allow } })
      setAnswer({ busy: true, error: '', redirect: res.redirect })
    } catch (err) {
      if (err.status === 401) expire()
      else setAnswer({ busy: false, error: err.message })
    }
  }

  if (!auth) return <Navigate to={`/login?next=${encodeURIComponent(pathname + search)}`} replace />
  if (error) return (
    <EmptyState icon={<CircleAlert strokeWidth={1.5} />} title={t.failed} action={<Button asChild><Link to="/">{t.home}</Link></Button>}>
      {error.message}
    </EmptyState>
  )
  if (!data || leaving) return <EmptyState icon={<LoaderCircle strokeWidth={1.5} className="motion-safe:animate-spin" />} title={leaving ? t.sending : t.busy} />
  return (
    <Page className="grid min-h-[60vh] place-items-center">
      <div className={cn(formCard, 'max-w-110')}>
        <div>
          <h1 className="text-[1.75rem]">{data.title}</h1>
          <p className="mt-1.5 text-muted-foreground">{data.lead}</p>
        </div>
        <p className={hint}>{data.returns_to} {t.warning}</p>
        {answer.error && <Fail>{answer.error}</Fail>}
        <div className="grid gap-3 sm:grid-cols-2">
          <Button variant="outline" disabled={answer.busy} onClick={() => send(false)}>{t.deny}</Button>
          <Button disabled={answer.busy} onClick={() => send(true)}>{t.allow}</Button>
        </div>
      </div>
    </Page>
  )
}
