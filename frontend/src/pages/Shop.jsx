import { Link, useSearchParams } from 'react-router-dom'
import { EmptyState, Status, TileGrid, useFetch } from '../components'

const SORTS = { '': 'Newest', price: 'Price, low to high', '-price': 'Price, high to low', '-rating': 'Best rated' }

export default function Shop() {
  const [params, setParams] = useSearchParams()
  const category = params.get('category') || ''
  const q = params.get('q') || ''
  const sort = params.get('sort') || ''
  const qs = new URLSearchParams(Object.entries({ category, q, sort }).filter(([, v]) => v)).toString()
  const products = useFetch(`/products/?${qs}`)
  const cats = useFetch('/categories/')
  const catName = cats.data?.find((c) => c.slug === category)?.name
  const title = q ? `Results for “${q}”` : catName || 'Every product'

  const set = (key, value) => {
    const next = new URLSearchParams(params)
    value ? next.set(key, value) : next.delete(key)
    setParams(next)
  }

  return (
    <section className="page shop">
      <div className="sec-head">
        <h1>{title}</h1>
        {products.data && <span className="soft">{products.data.length} {products.data.length === 1 ? 'item' : 'items'}</span>}
      </div>
      <div className="filters">
        <nav aria-label="Categories" className="cat-links">
          <Link to="/shop" aria-current={!category ? 'page' : undefined}>All</Link>
          {(cats.data || []).map((c) => (
            <Link key={c.slug} to={`/shop?category=${c.slug}`} aria-current={c.slug === category ? 'page' : undefined}>{c.name}</Link>
          ))}
        </nav>
        <label className="sort">
          Sort
          <select value={sort} onChange={(e) => set('sort', e.target.value)}>
            {Object.entries(SORTS).map(([v, label]) => <option key={v} value={v}>{label}</option>)}
          </select>
        </label>
      </div>
      <Status loading={products.loading} error={products.error}>
        {products.data?.length ? <TileGrid products={products.data} key={qs} /> : (
          <EmptyState icon="⌕" title="No products found" action={<Link to="/shop" className="btn btn--paper">Clear filters</Link>}>
            {q ? `Nothing matches “${q}”. Try a shorter or different word.` : 'This category has nothing in stock right now.'}
          </EmptyState>
        )}
      </Status>
    </section>
  )
}
