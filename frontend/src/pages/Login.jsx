import { useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { cn } from 'cn'
import { api } from '../api'
import Fail from '../components/Fail'
import Page from '../components/Page'
import { Button } from '../components/ui/button'
import { Input } from '../components/ui/input'
import { Label } from '../components/ui/label'
import { formCard, hint } from '../lib/styles'
import { useStore } from '../useStore'

export default function Login() {
  const [mode, setMode] = useState('login')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [show, setShow] = useState(false)
  const { login, config } = useStore()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const words = config.text.login
  const t = words[mode]

  const submit = async (e) => {
    e.preventDefault()
    setBusy(true)
    setError('')
    const body = Object.fromEntries(new FormData(e.currentTarget))
    try {
      const res = await api(mode === 'login' ? '/auth/login/' : '/auth/register/', { method: 'POST', body })
      login({ token: res.token, username: res.username, greeting: res.greeting })
      navigate(res.next, { replace: true }) // the server checked it is a same-site path
    } catch (err) {
      setError(err.message)
      setBusy(false)
    }
  }

  return (
    <Page className="grid min-h-[60vh] place-items-center">
      <form className={cn(formCard, 'max-w-110')} onSubmit={submit}>
        <div>
          <h1 className="text-[1.75rem]">{t.title}</h1>
          <p className="mt-1.5 text-muted-foreground">{t.lead}</p>
        </div>
        <input type="hidden" name="next" value={params.get('next') || ''} />
        <Label>{t.username}<Input className="font-normal" name="username" required autoComplete="username" /></Label>
        {mode === 'register' && <Label>{t.email}<Input className="font-normal" name="email" type="email" required autoComplete="email" /></Label>}
        <Label>{words.password}
          <span className="relative block">
            <Input className="pr-18 font-normal" name="password" type={show ? 'text' : 'password'} required
              autoComplete={mode === 'login' ? 'current-password' : 'new-password'} />
            <Button type="button" variant="link" size="inline" className="absolute top-1/2 right-1 h-10 -translate-y-1/2 px-3 text-small"
              onClick={() => setShow(!show)} aria-pressed={show}>{show ? words.hide : words.show}</Button>
          </span>
          {mode === 'register' && <span className={hint}>{config.password_rules.join(' ')}</span>}
        </Label>
        {error && <Fail>{error}</Fail>}
        <Button className="w-full" disabled={busy}>{busy ? words.busy : t.submit}</Button>
        <Button type="button" variant="link" size="inline" className="justify-self-center" onClick={() => { setMode(mode === 'login' ? 'register' : 'login'); setError('') }}>
          {t.switch}
        </Button>
        {params.get('next') === '/checkout' && <Button asChild variant="link" size="inline" className="justify-self-center"><Link to="/checkout">{words.guest}</Link></Button>}
      </form>
    </Page>
  )
}
