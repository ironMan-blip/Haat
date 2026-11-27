import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api, useFetch } from '../api'
import { useStore } from '../useStore'

// Anyone reads; only signed-in customers see the form. The server enforces the same rule.
export default function Comments({ slug }) {
  const path = `/products/${slug}/comments/`
  const { data } = useFetch(path) // no token: a stale one must not hide the comments
  const { auth, expire } = useStore()
  const [added, setAdded] = useState([]) // posted on this visit, shown above the loaded ones
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async (e) => {
    e.preventDefault()
    const form = e.currentTarget
    setBusy(true)
    setError('')
    try {
      const c = await api(path, { method: 'POST', body: { text: form.text.value }, token: auth.token })
      setAdded((a) => [c, ...a])
      form.reset()
    } catch (err) {
      if (err.status === 401) expire() // stale token: the login link replaces the form
      setError(err.message)
    }
    setBusy(false)
  }

  if (!data) return null
  const list = [...added, ...data.results]
  return (
    <section className="page comments">
      <div className="sec-head"><h2>{data.title}</h2></div>
      {auth ? (
        <form className="form" onSubmit={submit}>
          <label>
            <span className="sr-only">{data.placeholder}</span>
            <textarea name="text" rows="3" maxLength="1000" required placeholder={data.placeholder} />
          </label>
          {error && <p className="alert" role="alert">{error}</p>}
          <button className="btn" disabled={busy}>{busy ? 'Posting…' : 'Post comment'}</button>
        </form>
      ) : (
        <p className="soft"><Link className="link" to={`/login?next=/p/${slug}`}>{data.login_prompt}</Link></p>
      )}
      {list.length === 0 ? <p className="soft">{data.empty}</p> : (
        <ul className="comment-list">
          {list.map((c) => (
            <li key={c.id}>
              <p className="soft"><strong>{c.author}</strong> · {c.date}</p>
              <p>{c.text}</p>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
