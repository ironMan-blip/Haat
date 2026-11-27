import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, useFetch } from '../api'
import { useStore } from '../useStore'

// Anyone reads; only signed-in customers post, reply, like, edit or delete. The server enforces the same rules.
export default function Comments({ slug }) {
  const { auth, expire } = useStore()
  const path = `/products/${slug}/comments/`
  const [round, setRound] = useState(0)
  // Sent with the token so the server can say which comments are mine and liked. `r` reloads after a change.
  const { data, error } = useFetch(`${path}?r=${round}`, auth?.token)
  const [fail, setFail] = useState('')

  useEffect(() => {
    if (error?.status === 401) expire() // stale token: refetches as a guest
  }, [error]) // eslint-disable-line react-hooks/exhaustive-deps -- expire is recreated every render

  // Runs one change, then reloads the thread. Resolves true when the server accepted it.
  const act = (url, opts) => api(url, { ...opts, token: auth?.token })
    .then(() => { setFail(''); setRound((n) => n + 1); return true })
    .catch((err) => { if (err.status === 401) expire(); setFail(err.message); return false })

  if (!data) return null
  const ctx = { data, auth, act, path }
  return (
    <section className="page comments">
      <div className="sec-head"><h2>{data.title}</h2></div>
      {fail && <p className="alert" role="alert">{fail}</p>}
      {auth ? (
        <CommentForm placeholder={data.placeholder} label="Post comment"
          submit={(text) => act(path, { method: 'POST', body: { text } })} />
      ) : (
        <p className="soft"><Link className="link" to={`/login?next=/p/${slug}`}>{data.login_prompt}</Link></p>
      )}
      {data.results.length === 0 ? <p className="soft">{data.empty}</p> : (
        <ul className="comment-list">
          {data.results.map((c) => <Comment key={c.id} c={c} ctx={ctx} />)}
        </ul>
      )}
    </section>
  )
}

function Comment({ c, ctx }) {
  const { data, auth, act, path } = ctx
  const [mode, setMode] = useState(null) // 'edit' | 'reply' | null
  const url = `/comments/${c.id}/`
  const done = (ok) => { if (ok) setMode(null); return ok }

  return (
    <li>
      {c.author && <p className="soft"><strong>{c.author}</strong> · {c.date}{c.edited_label && ` · ${c.edited_label}`}</p>}
      {mode === 'edit' ? (
        <CommentForm text={c.text} placeholder={data.placeholder} label="Save" cancel={() => setMode(null)}
          submit={(text) => act(url, { method: 'PATCH', body: { text } }).then(done)} />
      ) : (
        <p className={c.deleted ? 'soft' : undefined}>{c.text}</p>
      )}
      {!c.deleted && mode !== 'edit' && (
        <div className="comment-actions">
          <button type="button" className="link" disabled={!auth} aria-pressed={c.liked}
            aria-label={`Like, ${c.likes}`} onClick={() => act(`${url}like/`, { method: c.liked ? 'DELETE' : 'POST' })}>
            {c.liked ? '♥' : '♡'} {c.likes}
          </button>
          {auth && c.replies && <button type="button" className="link" onClick={() => setMode('reply')}>Reply</button>}
          {c.mine && (
            <>
              <button type="button" className="link" onClick={() => setMode('edit')}>Edit</button>
              <button type="button" className="link link--danger"
                onClick={() => window.confirm(data.delete_confirm) && act(url, { method: 'DELETE' })}>Delete</button>
            </>
          )}
        </div>
      )}
      {c.replies?.length > 0 && (
        <ul className="comment-list comment-replies">
          {c.replies.map((r) => <Comment key={r.id} c={r} ctx={ctx} />)}
        </ul>
      )}
      {mode === 'reply' && (
        <CommentForm placeholder={data.reply_placeholder} label="Reply" cancel={() => setMode(null)}
          submit={(text) => act(path, { method: 'POST', body: { text, parent: c.id } }).then(done)} />
      )}
    </li>
  )
}

function CommentForm({ text = '', placeholder, label, submit, cancel }) {
  const [busy, setBusy] = useState(false)
  const onSubmit = async (e) => {
    e.preventDefault()
    const form = e.currentTarget
    setBusy(true)
    if (await submit(form.text.value)) form.reset()
    setBusy(false)
  }
  return (
    <form className="form" onSubmit={onSubmit}>
      <label>
        <span className="sr-only">{placeholder}</span>
        <textarea name="text" rows="3" maxLength="1000" required placeholder={placeholder} defaultValue={text}
          autoFocus={Boolean(cancel)} />
      </label>
      <div className="comment-actions">
        <button className="btn" disabled={busy}>{busy ? 'Saving…' : label}</button>
        {cancel && <button type="button" className="link" onClick={cancel}>Cancel</button>}
      </div>
    </form>
  )
}
