import { SearchX } from 'lucide-react'
import { Link, useSearchParams } from 'react-router-dom'
import { useFetch } from '../api'
import EmptyState from '../components/EmptyState'
import Page from '../components/Page'
import Status from '../components/Status'
import { Button } from '../components/ui/button'
import { NativeSelect, NativeSelectOption } from '../components/ui/native-select'
import { pill } from '../lib/styles'
import TileGrid from '../components/TileGrid'
import { useStore } from '../useStore'

const cat = `${pill} border bg-background hover:border-primary hover:text-primary aria-[current=page]:border-primary aria-[current=page]:bg-primary aria-[current=page]:text-primary-foreground`

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
    <Page>
      <div className="mb-6 flex flex-wrap items-baseline justify-between gap-4">
        <h1>{data?.title ?? ' '}</h1>
        {data && <span className="text-muted-foreground">{data.count_label}</span>}
      </div>
      <div className="mb-7 flex flex-wrap items-center justify-between gap-4 border-b pb-5">
        {/* Phones: one swipeable row, so products stay near the top. */}
        <nav aria-label="Categories" className="flex gap-2 *:flex-none max-md:-mx-gutter max-md:w-[calc(100%+2*var(--spacing-gutter))] max-md:overflow-x-auto max-md:px-gutter max-md:[scrollbar-width:none] md:flex-wrap">
          <Link className={cat} to="/shop" aria-current={!category ? 'page' : undefined}>All</Link>
          {(data?.categories || []).map((c) => (
            <Link className={cat} key={c.slug} to={`/shop?category=${c.slug}`} aria-current={c.slug === category ? 'page' : undefined}>{c.name}</Link>
          ))}
        </nav>
        <label className="flex items-center gap-2.5 font-medium">
          Sort
          <NativeSelect value={sort} onChange={(e) => set('sort', e.target.value)}>
            {(config?.sorts || []).map((s) => <NativeSelectOption key={s.value} value={s.value}>{s.label}</NativeSelectOption>)}
          </NativeSelect>
        </label>
      </div>
      <Status loading={loading} error={error}>
        {data?.results.length ? <TileGrid products={data.results} key={qs} /> : (
          <EmptyState icon={<SearchX strokeWidth={1.5} />} title="No products found" action={<Button asChild variant="outline"><Link to="/shop">Clear filters</Link></Button>}>
            {data?.empty}
          </EmptyState>
        )}
      </Status>
    </Page>
  )
}
