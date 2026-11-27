import { Link } from 'react-router-dom'
import { cn } from 'cn'
import { useFetch } from '../api'
import Page from '../components/Page'
import Reveal from '../components/Reveal'
import Status from '../components/Status'
import TileGrid from '../components/TileGrid'
import { Button } from '../components/ui/button'
import { pill, textLink } from '../lib/styles'
import { useStore } from '../useStore'

// Price-tag colours the server names per tile.
const field = {
  f1: 'bg-primary text-primary-foreground',
  f2: 'bg-warn-soft text-warn',
  f3: 'bg-secondary text-secondary-foreground',
}
const wallTile = 'grid aspect-square w-[22vw] flex-none place-items-center overflow-hidden rounded-xl bg-background md:w-[max(112px,7.8vw)]'

// Brickwork wall of goods and price tags, like a haat laid out on the ground.
function Wall({ rows }) {
  return (
    <div className="grid h-65 gap-1.5 overflow-hidden pt-2.5 motion-safe:animate-drift md:h-auto md:gap-2.5 md:overflow-visible" aria-hidden="true">
      {rows.map((row, r) => (
        <div className="flex gap-1.5 even:-translate-x-15 md:gap-2.5" key={r}>
          {row.map((b, c) =>
            b.tag ? (
              <span key={c} className={cn(wallTile, 'text-lg font-bold tracking-[-0.01em]', field[b.field])}>{b.tag}</span>
            ) : (
              <span key={c} className={wallTile}><img className="aspect-square w-[72%] object-contain mix-blend-multiply" src={b.image} alt="" width="112" height="112" /></span>
            ))}
        </div>
      ))}
    </div>
  )
}

function Showcase({ items }) {
  const { add } = useStore()
  return (
    <section className="mx-auto grid w-full max-w-site gap-[clamp(12px,2vw,20px)] px-gutter md:grid-cols-2">
      {items.map((p, i) => (
        <Reveal key={p.id} className={cn(
          'relative aspect-[4/5] overflow-hidden rounded-2xl md:aspect-auto md:h-[min(80svh,680px)] md:min-h-130',
          i ? 'border bg-background' : 'bg-muted',
        )}>
          {i === 0 && <h2 className="absolute top-6 left-6 z-1 rounded-full bg-foreground px-3.5 py-1.5 text-small tracking-normal text-background">Best rated</h2>}
          <img className="absolute top-0 left-[5%] w-[90%] max-w-none mix-blend-multiply" src={p.image_large} alt={p.name} loading="lazy" width="800" height="800" />
          <div className="absolute inset-x-4 bottom-4 flex flex-col items-stretch gap-5 rounded-xl bg-background p-5 shadow-soft md:flex-row md:items-end md:justify-between">
            <div>
              <Link to={`/p/${p.slug}`} className="text-lg font-semibold no-underline hover:underline">{p.panel_name}</Link>
              <p className="mt-1 text-small text-muted-foreground">{p.panel_fact}</p>
            </div>
            <div className="flex flex-none gap-2 *:flex-1 md:*:flex-none">
              {p.choose_label
                ? <Button asChild><Link to={`/p/${p.slug}`}>{p.choose_label}</Link></Button>
                : <Button onClick={() => add(p)}>Add to cart</Button>}
              <Button asChild variant="outline"><Link to={`/p/${p.slug}`}>View</Link></Button>
            </div>
          </div>
        </Reveal>
      ))}
    </section>
  )
}

function Menu({ menu }) {
  return (
    <Page>
      {menu.map((cat) => (
        <Reveal className="mt-[clamp(48px,6vw,80px)]" key={cat.slug} id={cat.slug}>
          <div className="mb-5 flex items-baseline justify-between gap-4">
            <h2><Link className="no-underline hover:text-primary" to={`/shop?category=${cat.slug}`}>{cat.name}</Link></h2>
            <span className="text-small text-muted-foreground">{cat.count_label}</span>
          </div>
          <ul className="grid grid-cols-[minmax(0,1fr)] gap-3 md:grid-cols-2">
            {cat.items.map((p) => (
              <li key={p.id}>
                <Link to={`/p/${p.slug}`} className="flex min-w-0 gap-4 rounded-xl border bg-background p-3.5 no-underline transition-[border-color,box-shadow] hover:border-transparent hover:shadow-soft">
                  <img className="size-13 flex-none rounded-lg bg-page object-contain mix-blend-multiply md:size-16" src={p.thumb} alt="" width="64" height="64" loading="lazy" />
                  <span className="grid min-w-0 flex-1 grid-cols-[minmax(0,1fr)] gap-0.5">
                    <span className="flex justify-between gap-4"><b className="min-w-0 truncate font-semibold">{p.name}</b><span className="flex-none font-bold">{p.price_display}</span></span>
                    <span className="line-clamp-2 text-small wrap-anywhere text-muted-foreground">{p.summary}</span>
                    {p.note && <span className="text-small font-medium wrap-anywhere text-destructive">{p.note}</span>}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </Reveal>
      ))}
    </Page>
  )
}

export default function Home() {
  const { data, loading, error } = useFetch('/home/') // server picks deals, best rated and the menu
  const { wall = [], deals = [], best = [], menu = [], hero, promise } = data || {}

  return (
    <Status loading={loading} error={error}>
      {wall.length > 0 && (
        <section className="relative overflow-hidden bg-muted pb-4 md:h-[min(78svh,760px)] md:min-h-130 md:pb-0 md:after:pointer-events-none md:after:absolute md:after:inset-0 md:after:bg-linear-to-b md:after:from-page/0 md:after:from-35% md:after:to-page/85">
          <Wall rows={wall} />
          <div className="relative z-1 mx-auto -mt-12 grid w-[calc(100%-2*var(--spacing-gutter))] items-center gap-x-8 gap-y-5 rounded-2xl bg-background p-[clamp(24px,3vw,40px)] shadow-float md:absolute md:bottom-8 md:left-1/2 md:mt-0 md:w-[min(80rem,calc(100%-2*var(--spacing-gutter)))] md:-translate-x-1/2 md:grid-cols-[1fr_auto]">
            <div>
              <h1 className="mb-2.5 text-[clamp(2rem,1.2rem+3vw,3.5rem)] leading-[1.05] tracking-[-0.035em]">{hero.head}</h1>
              <p className="text-lead leading-[1.4] text-muted-foreground">{hero.line}</p>
            </div>
            <Button asChild size="lg" className="w-full md:w-auto"><Link to="/shop">Start shopping</Link></Button>
            <nav className="col-span-full flex flex-wrap gap-2 border-t pt-5" aria-label="Categories">
              {menu.map((c) => <Link key={c.slug} className={cn(pill, 'bg-muted px-3.5 text-small hover:bg-secondary hover:text-secondary-foreground')} to={`/shop?category=${c.slug}`}>{c.name}</Link>)}
            </nav>
          </div>
        </section>
      )}

      <Page>
        <Reveal className="mb-6 flex flex-wrap items-baseline justify-between gap-4">
          <h2>Today's best deals</h2>
          <Link to="/shop?sort=price" className={textLink}>See all →</Link>
        </Reveal>
        <TileGrid products={deals} feature />
      </Page>

      {best.length === 2 && <Showcase items={best} />}

      {promise && (
        <section className="mx-auto mt-[clamp(48px,7vw,96px)] w-full max-w-site px-gutter">
          <Reveal>
            <p className="rounded-2xl bg-primary p-[clamp(32px,5vw,64px)] text-[clamp(1.25rem,1rem+1vw,1.875rem)] leading-[1.35] font-semibold tracking-[-0.01em] text-primary-foreground">{promise}</p>
          </Reveal>
        </section>
      )}

      <Menu menu={menu} />
    </Status>
  )
}
