import { useEffect, useState } from 'react'
import { Heart } from 'lucide-react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { useStore } from '../useStore'
import Page from './Page'
import Fail from './Fail'
import { Button } from './ui/button'
import { Label } from './ui/label'
import { Skeleton } from './ui/skeleton'
import { Textarea } from './ui/textarea'

const danger = 'text-muted-foreground hover:text-destructive'

// Server order: threads newest first, replies oldest first. Ids only grow, so sorting by id keeps it.
const merge = (list, more, dir) => {
  const have = new Set(list.map((c) => c.id))
  return [...list, ...more.filter((c) => !have.has(c.id))].sort((a, b) => dir * (a.id - b.id))
}
// Applies a changed comment (edit, like, placeholder) wherever it is in the loaded threads.
const swap = (list, c) => list.map((t) => (t.id === c.id ? { ...t, ...c } : t.replies ? { ...t, replies: swap(t.replies, c) } : t))
// Removes comments by id, replies included; the server sends the thread's new counts separately.
const drop = (list, ids) => list.filter((t) => !ids.includes(t.id)).map((t) => (t.replies ? { ...t, replies: drop(t.replies, ids) } : t))

// Anyone reads; only signed-in customers post, reply, like, edit or delete. The server enforces the same rules.
// Loads 10 threads (each with its first 10 replies, folded behind a toggle); "See more" fetches the next 10 of either.
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
      const { title, thread, ...c } = res // a reply comes with its thread's new counts; a new thread comes empty
      setPage((p) => ({ ...p, title }))
      setThreads((ts) => (parent ? ts.map((t) => (t.id === parent ? { ...t, ...thread, replies: merge(t.replies, [c], 1) } : t))
        : merge(ts, [c], -1)))
      return true
    }),
    change: (url, opts) => run(url, opts).then((c) => { if (c) setThreads((ts) => swap(ts, c)); return Boolean(c) }),
    remove: (c) => run(`/comments/${c.id}/`, { method: 'DELETE' }).then((res) => {
      if (!res) return
      setPage((p) => ({ ...p, title: res.title }))
      setThreads((ts) => drop([res.comment, res.thread].reduce((l, x) => (x ? swap(l, x) : l), ts), res.removed))
    }),
    moreReplies: (t) => run(`/comments/${t.id}/replies/?after=${t.replies_next}`).then((d) => {
      if (d) setThreads((ts) => ts.map((x) => (x.id === t.id ? { ...x, replies: merge(x.replies, d.results, 1), replies_next: d.next } : x)))
    }),
  }
  const moreThreads = () => run(`${path}?before=${page.next}`).then((d) => {
    if (d) { setThreads((ts) => merge(ts, d.results, -1)); setPage((p) => ({ ...p, next: d.next })) }
  })

  if (loadError) return <Page className="grid max-w-190 gap-5"><Fail>{loadError}</Fail></Page>
  if (!page) return ( // loading, or a stale token being dropped
    <Page className="grid max-w-190 gap-3" aria-busy="true" aria-label="Loading comments">
      <Skeleton className="mb-2 h-8 w-48" />
      {[0, 1].map((i) => <Skeleton key={i} className="h-24 rounded-xl" />)}
    </Page>
  )
  return (
    <Page className="grid max-w-190 gap-5">
      <h2>{page.title}</h2>
      {fail && <Fail>{fail}</Fail>}
      {auth ? (
        <CommentForm placeholder={page.placeholder} label="Post comment" submit={(text) => ctx.post(text)} />
      ) : (
        <p className="text-muted-foreground"><Button asChild variant="link" size="inline"><Link to={`/login?next=/p/${slug}`}>{page.login_prompt}</Link></Button></p>
      )}
      {threads.length === 0 ? <p className="text-muted-foreground">{page.empty}</p> : (
        <ul className="grid gap-3">
          {threads.map((c) => <Comment key={c.id} c={c} ctx={ctx} />)}
        </ul>
      )}
      {page.next && <More label={page.more_label} load={moreThreads} />}
    </Page>
  )
}

function Comment({ c, ctx }) {
  const { page, auth } = ctx
  const [mode, setMode] = useState(null) // 'edit' | 'reply' | 'delete' (asking to confirm) | null
  const [open, setOpen] = useState(false) // replies shown
  const url = `/comments/${c.id}/`
  const done = (ok) => { if (ok) setMode(null); return ok }

  return (
    <li className="grid gap-2 rounded-xl border bg-background px-5 py-4 whitespace-pre-line wrap-anywhere">
      {c.author && <p className="text-muted-foreground"><strong>{c.author}</strong> · {c.date}{c.edited_label && ` · ${c.edited_label}`}</p>}
      {mode === 'edit' ? (
        <CommentForm text={c.text} placeholder={page.placeholder} label="Save" cancel={() => setMode(null)}
          submit={(text) => ctx.change(url, { method: 'PATCH', body: { text } }).then(done)} />
      ) : (
        <p className={c.deleted ? 'text-muted-foreground' : undefined}>{c.text}</p>
      )}
      {!c.deleted && mode !== 'edit' && (
        <div className="flex flex-wrap items-center gap-4 whitespace-normal">
          <Button type="button" variant="link" size="inline" className="gap-1" disabled={!auth} aria-pressed={c.liked} aria-label={`Like, ${c.likes}`}
            onClick={() => ctx.change(`${url}like/`, { method: c.liked ? 'DELETE' : 'POST' })}>
            <Heart aria-hidden="true" strokeWidth={1.75} className={c.liked ? 'fill-current' : undefined} /> {c.likes}
          </Button>
          {auth && !c.is_reply && <Button type="button" variant="link" size="inline" onClick={() => setMode('reply')}>Reply</Button>}
          {c.mine && mode !== 'delete' && (
            <>
              <Button type="button" variant="link" size="inline" onClick={() => setMode('edit')}>Edit</Button>
              <Button type="button" variant="link" size="inline" className={danger} onClick={() => setMode('delete')}>Delete</Button>
            </>
          )}
          {mode === 'delete' && (
            <span className="flex flex-wrap items-center gap-4 rounded-lg bg-sale-soft px-3 py-2" role="alert">
              <span className="font-medium">{page.delete_confirm}</span>
              <Button type="button" size="sm" className="bg-destructive text-white hover:bg-destructive/90" autoFocus onClick={() => ctx.remove(c).then(() => setMode(null))}>Delete</Button>
              <Button type="button" variant="link" size="inline" onClick={() => setMode(null)}>Cancel</Button>
            </span>
          )}
        </div>
      )}
      {c.replies_label && (
        <Button type="button" variant="link" size="inline" className="justify-self-start" aria-expanded={open} onClick={() => setOpen(!open)}>
          {open ? page.hide_replies_label : c.replies_label} {open ? '▴' : '▾'}
        </Button>
      )}
      {open && c.replies?.length > 0 && (
        <ul className="ml-[clamp(12px,3vw,32px)] grid gap-3 [&>li]:bg-transparent">
          {c.replies.map((r) => <Comment key={r.id} c={r} ctx={ctx} />)}
        </ul>
      )}
      {open && c.replies_next && <More label={page.more_replies_label} load={() => ctx.moreReplies(c)} />}
      {mode === 'reply' && (
        <CommentForm placeholder={page.reply_placeholder} label="Reply" cancel={() => setMode(null)}
          submit={(text) => ctx.post(text, c.id).then((ok) => { if (ok) setOpen(true); return done(ok) })} />
      )}
    </li>
  )
}

function More({ label, load }) {
  const [busy, setBusy] = useState(false)
  return (
    <Button type="button" variant="line" className="justify-self-start whitespace-normal" disabled={busy}
      onClick={() => { setBusy(true); load().finally(() => setBusy(false)) }}>
      {busy ? 'Loading…' : label}
    </Button>
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
    <form className="grid max-w-150 gap-4.5" onSubmit={onSubmit}>
      <Label>
        <span className="sr-only">{placeholder}</span>
        <Textarea className="resize-y font-normal" name="text" rows="3" maxLength="1000" required placeholder={placeholder} defaultValue={text}
          autoFocus={Boolean(cancel)} />
      </Label>
      <div className="flex flex-wrap items-center gap-4">
        <Button disabled={busy}>{busy ? 'Saving…' : label}</Button>
        {cancel && <Button type="button" variant="link" size="inline" onClick={cancel}>Cancel</Button>}
      </div>
    </form>
  )
}
