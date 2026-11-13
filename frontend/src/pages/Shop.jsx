import { Link, useSearchParams } from 'react-router-dom'
import { useFetch } from '../api'
import EmptyState from '../components/EmptyState'
import Status from '../components/Status'
import TileGrid from '../components/TileGrid'
import { useStore } from '../useStore'

export default function Shop() {
  const [params, setParams] = useSearchParams()
  const { config } = useStore()
  const category = params.get('category') || ''
  const sort = params.get('sort') || ''
  const qs = params.toString()
  // The server sends the heading, item count, category links and empty-state text with the results.
  const { data, loading, error } = useFetch(`/products/?${qs}`)

  const set = (key, value) => {
    const next = new URLSearchParams(params)
    value ? next.set(key, value) : next.delete(key)
    setParams(next)
  }

  return (
    <section className="page shop">
      <div className="sec-head">
        <h1>{data?.title ?? ' '}</h1>
        {data && <span className="soft">{data.count_label}</span>}
      </div>
      <div className="filters">
        <nav aria-label="Categories" className="cat-links">
          <Link to="/shop" aria-current={!category ? 'page' : undefined}>All</Link>
          {(data?.categories || []).map((c) => (
            <Link key={c.slug} to={`/shop?category=${c.slug}`} aria-current={c.slug === category ? 'page' : undefined}>{c.name}</Link>
          ))}
        </nav>
        <label className="sort">
          Sort
          <select value={sort} onChange={(e) => set('sort', e.target.value)}>
            {(config?.sorts || []).map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
          </select>
        </label>
      </div>
      <Status loading={loading} error={error}>
        {data?.results.length ? <TileGrid products={data.results} key={qs} /> : (
          <EmptyState icon="⌕" title="No products found" action={<Link to="/shop" className="btn btn--paper">Clear filters</Link>}>
            {data?.empty}
          </EmptyState>
        )}
      </Status>
    </section>
  )
}
