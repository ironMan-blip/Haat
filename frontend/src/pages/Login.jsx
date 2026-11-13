import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '../api'
import { useStore } from '../store'

export default function Login() {
  const [mode, setMode] = useState('login')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const { login } = useStore()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const next = params.get('next')?.startsWith('/') ? params.get('next') : '/' // no open redirect

  const submit = async (e) => {
    e.preventDefault()
    setBusy(true)
    setError('')
    const body = Object.fromEntries(new FormData(e.currentTarget))
    try {
      const res = await api(mode === 'login' ? '/auth/login/' : '/auth/register/', { method: 'POST', body })
      login({ token: res.token, username: res.username })
      navigate(next, { replace: true })
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
        <label>Username<input name="username" required autoComplete="username" /></label>
        {mode === 'register' && <label>Email <span className="hint">(optional)</span><input name="email" type="email" autoComplete="email" /></label>}
        <label>Password
          <input name="password" type="password" required minLength={8}
            autoComplete={mode === 'login' ? 'current-password' : 'new-password'} />
          {mode === 'register' && <span className="hint">At least 8 characters.</span>}
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
