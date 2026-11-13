import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '../api'
import { useStore } from '../useStore'

export default function Login() {
  const [mode, setMode] = useState('login')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [show, setShow] = useState(false)
  const { login, config } = useStore()
  const navigate = useNavigate()
  const [params] = useSearchParams()

  const submit = async (e) => {
    e.preventDefault()
    setBusy(true)
    setError('')
    const body = Object.fromEntries(new FormData(e.currentTarget))
    try {
      const res = await api(mode === 'login' ? '/auth/login/' : '/auth/register/', { method: 'POST', body })
      login({ token: res.token, username: res.username })
      navigate(res.next, { replace: true }) // the server checked it is a same-site path
    } catch (err) {
      setError(err.message)
      setBusy(false)
    }
  }

  return (
    <section className="page auth">
      <form className="form form-card" onSubmit={submit}>
        <div>
          <h1>{mode === 'login' ? 'Welcome back' : 'Create an account'}</h1>
          <p className="soft">{mode === 'login' ? 'Log in to check out and track your orders.' : 'It takes less than a minute.'}</p>
        </div>
        <input type="hidden" name="next" value={params.get('next') || ''} />
        <label>Username<input name="username" required autoComplete="username" /></label>
        {mode === 'register' && <label>Email <span className="hint">(optional)</span><input name="email" type="email" autoComplete="email" /></label>}
        <label>Password
          <span className="pw">
            <input name="password" type={show ? 'text' : 'password'} required
              autoComplete={mode === 'login' ? 'current-password' : 'new-password'} />
            <button type="button" className="link" onClick={() => setShow(!show)} aria-pressed={show}>{show ? 'Hide' : 'Show'}</button>
          </span>
          {mode === 'register' && config && <span className="hint">{config.password_rules.join(' ')}</span>}
        </label>
        {error && <p className="alert" role="alert">{error}</p>}
        <button className="btn btn--wide" disabled={busy}>{busy ? 'Please wait…' : mode === 'login' ? 'Log in' : 'Create account'}</button>
        <button type="button" className="link" onClick={() => { setMode(mode === 'login' ? 'register' : 'login'); setError('') }}>
          {mode === 'login' ? 'New here? Create an account' : 'Have an account? Log in'}
        </button>
      </form>
    </section>
  )
}
