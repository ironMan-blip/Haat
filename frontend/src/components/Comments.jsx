import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { useStore } from '../useStore'

// Server order: threads newest first, replies oldest first. Ids only grow, so sorting by id keeps it.
const merge = (list, more, dir) => {
  const have = new Set(list.map((c) => c.id))
  return [...list, ...more.filter((c) => !have.has(c.id))].sort((a, b) => dir * (a.id - b.id))
}
// Applies a changed comment (edit, like, placeholder) wherever it is in the loaded threads.
const swap = (list, c) => list.map((t) => (t.id === c.id ? { ...t, ...c } : t.replies ? { ...t, replies: swap(t.replies, c) } : t))
const drop = (list, ids) => list.filter((t) => !ids.includes(t.id)).map((t) => (t.replies ? { ...t, replies: drop(t.replies, ids) } : t))

// Anyone reads; only signed-in customers post, reply, like, edit or delete. The server enforces the same rules.
// Loads 10 threads (each with its first 10 replies); "See more" fetches the next 10 of either.
export default function Comments({ slug }) {
  const { auth, expire } = useStore()
  const path = `/products/${slug}/comments/`
  const [page, setPage] = useState(null) // the first response: labels, title, cursor
  const [threads, setThreads] = useState([])
  const [loadError, setLoadError] = useState('')
  const [fail, setFail] = useState('')

  // Sent with the token so the server can say which comments are mine and liked; signing in or out reloads.
  useEffect(() => {
    let live = true
    api(path, { token: auth?.token })
      .then((d) => { if (live) { setPage(d); setThreads(d.results); setLoadError('') } })
      .catch((err) => { if (!live) return; if (err.status === 401) expire(); else setLoadError(err.message) })
    return () => { live = false }
  }, [path, auth?.token]) // eslint-disable-line react-hooks/exhaustive-deps -- expire is recreated every render

  // One request; resolves with the server's answer, or null after showing why it failed.
  const run = (url, opts) => api(url, { ...opts, token: auth?.token })
    .then((d) => { setFail(''); return d })
    .catch((err) => { if (err.status === 401) expire(); setFail(err.message); return null })

  const ctx = {
    page, auth,
    post: (text, parent) => run(path, { method: 'POST', body: { text, parent } }).then((res) => {
      if (!res) return false
      const { title, ...c } = res
      setPage((p) => ({ ...p, title }))
      setThreads((ts) => (parent ? ts.map((t) => (t.id === parent ? { ...t, replies: merge(t.replies, [c], 1) } : t))
        : merge(ts, [{ ...c, replies: [], replies_next: null }], -1)))
      return true
    }),
    change: (url, opts) => run(url, opts).then((c) => { if (c) setThreads((ts) => swap(ts, c)); return Boolean(c) }),
    remove: (c) => run(`/comments/${c.id}/`, { method: 'DELETE' }).then((res) => {
      if (!res) return
      setPage((p) => ({ ...p, title: res.title }))
      setThreads((ts) => drop(res.comment ? swap(ts, res.comment) : ts, res.removed))
    }),
    moreReplies: (t) => run(`/comments/${t.id}/replies/?after=${t.replies_next}`).then((d) => {
      if (d) setThreads((ts) => ts.map((x) => (x.id === t.id ? { ...x, replies: merge(x.replies, d.results, 1), replies_next: d.next } : x)))
    }),
  }
  const moreThreads = () => run(`${path}?before=${page.next}`).then((d) => {
    if (d) { setThreads((ts) => merge(ts, d.results, -1)); setPage((p) => ({ ...p, next: d.next })) }
  })

  if (loadError) return <section className="page comments"><p className="alert" role="alert">{loadError}</p></section>
  if (!page) return null // loading, or a stale token being dropped
  return (
    <section className="page comments">
      <div className="sec-head"><h2>{page.title}</h2></div>
      {fail && <p className="alert" role="alert">{fail}</p>}
      {auth ? (
        <CommentForm placeholder={page.placeholder} label="Post comment" submit={(text) => ctx.post(text)} />
      ) : (
        <p className="soft"><Link className="link" to={`/login?next=/p/${slug}`}>{page.login_prompt}</Link></p>
      )}
      {threads.length === 0 ? <p className="soft">{page.empty}</p> : (
        <ul className="comment-list">
          {threads.map((c) => <Comment key={c.id} c={c} ctx={ctx} />)}
        </ul>
      )}
      {page.next && <More label={page.more_label} load={moreThreads} />}
    </section>
  )
}

function Comment({ c, ctx }) {
  const { page, auth } = ctx
  const [mode, setMode] = useState(null) // 'edit' | 'reply' | null
  const url = `/comments/${c.id}/`
  const done = (ok) => { if (ok) setMode(null); return ok }

  return (
    <li>
      {c.author && <p className="soft"><strong>{c.author}</strong> · {c.date}{c.edited_label && ` · ${c.edited_label}`}</p>}
      {mode === 'edit' ? (
        <CommentForm text={c.text} placeholder={page.placeholder} label="Save" cancel={() => setMode(null)}
          submit={(text) => ctx.change(url, { method: 'PATCH', body: { text } }).then(done)} />
      ) : (
        <p className={c.deleted ? 'soft' : undefined}>{c.text}</p>
      )}
      {!c.deleted && mode !== 'edit' && (
        <div className="comment-actions">
          <button type="button" className="link" disabled={!auth} aria-pressed={c.liked} aria-label={`Like, ${c.likes}`}
            onClick={() => ctx.change(`${url}like/`, { method: c.liked ? 'DELETE' : 'POST' })}>
            {c.liked ? '♥' : '♡'} {c.likes}
          </button>
          {auth && !c.is_reply && <button type="button" className="link" onClick={() => setMode('reply')}>Reply</button>}
          {c.mine && (
            <>
              <button type="button" className="link" onClick={() => setMode('edit')}>Edit</button>
              <button type="button" className="link link--danger"
                onClick={() => window.confirm(page.delete_confirm) && ctx.remove(c)}>Delete</button>
            </>
          )}
        </div>
      )}
      {c.replies?.length > 0 && (
        <ul className="comment-list comment-replies">
          {c.replies.map((r) => <Comment key={r.id} c={r} ctx={ctx} />)}
        </ul>
      )}
      {c.replies_next && <More label={page.more_replies_label} load={() => ctx.moreReplies(c)} />}
      {mode === 'reply' && (
        <CommentForm placeholder={page.reply_placeholder} label="Reply" cancel={() => setMode(null)}
          submit={(text) => ctx.post(text, c.id).then(done)} />
      )}
    </li>
  )
}

function More({ label, load }) {
  const [busy, setBusy] = useState(false)
  return (
    <button type="button" className="btn btn--line comment-more" disabled={busy}
      onClick={() => { setBusy(true); load().finally(() => setBusy(false)) }}>
      {busy ? 'Loading…' : label}
    </button>
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
