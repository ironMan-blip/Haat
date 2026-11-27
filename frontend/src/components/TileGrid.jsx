import { Plus } from 'lucide-react'
import { Link } from 'react-router-dom'
import { cn } from 'cn'
import { useStore } from '../useStore'
import Rating from './Rating'
import Reveal from './Reveal'
import { Badge } from './ui/badge'
import { Button } from './ui/button'

const grid = 'grid grid-flow-dense grid-cols-[repeat(auto-fill,minmax(min(200px,42vw),1fr))] gap-[clamp(12px,2vw,20px)]'
export const Grid = ({ className, ...rest }) => <div className={cn(grid, className)} {...rest} />

const add = 'relative z-1 text-primary hover:border-primary hover:bg-primary hover:text-primary-foreground active:scale-94'

// The name link stretches over the whole tile (::after); the add button sits above it.
function Tile({ p, big }) {
  const { add: addToCart } = useStore()
  const out = p.stock_level === 'out'
  return (
    <article className={cn(
      'group/tile relative flex flex-col gap-1.5 rounded-xl border bg-background px-2.5 pt-2.5 pb-3.5',
      'hover:-translate-y-0.5 hover:border-transparent hover:shadow-soft motion-reduce:hover:translate-y-0 has-[>a:focus-visible]:outline-3 has-[>a:focus-visible]:outline-offset-2 has-[>a:focus-visible]:outline-ring',
      big && 'col-span-2 md:row-span-2',
    )}>
      <span className="relative mb-1.5 grid aspect-square place-items-center overflow-hidden rounded-lg bg-page">
        <img src={p.image} alt="" loading="lazy" width="400" height="400"
          className={cn('aspect-square w-[82%] object-contain mix-blend-multiply transition-transform duration-320 ease-haat group-hover/tile:scale-105', out && 'opacity-45')} />
        {p.badge && <Badge className={cn('absolute top-2 left-2 rounded-md font-bold text-white', out ? 'bg-foreground' : 'bg-destructive')}>{p.badge}</Badge>}
      </span>
      <Link to={`/p/${p.slug}`} className={cn(
        'line-clamp-2 px-1 text-[0.9375rem] leading-[1.4] font-medium no-underline group-hover/tile:text-primary after:absolute after:inset-0 after:rounded-[inherit] focus-visible:outline-none',
        big && 'text-lead',
      )}>{p.name}</Link>
      <span className="px-1"><Rating p={p} /></span>
      <span className="mt-auto flex items-center justify-between gap-2 pl-1">
        <span className={cn('text-[1.0625rem] leading-tight font-bold', out && 'text-muted-foreground')}>
          {p.price_display}
          {p.original_price_display && <> <s>{p.original_price_display}</s></>}
        </span>
        {!out && (p.choose_label ? (
          <Button asChild variant="outline" size="icon" className={add}>
            <Link to={`/p/${p.slug}`} aria-label={`${p.choose_label}: ${p.name}`}><Plus aria-hidden="true" strokeWidth={1.75} /></Link>
          </Button>
        ) : (
          <Button type="button" variant="outline" size="icon" className={add} onClick={() => addToCart(p)} aria-label={`Add ${p.name} to cart`}>
            <Plus aria-hidden="true" strokeWidth={1.75} />
          </Button>
        ))}
      </span>
    </article>
  )
}

// `feature` enlarges every 7th tile: for short curated rows, not for long lists people scan.
export default function TileGrid({ products, feature }) {
  return (
    <Reveal className={grid}>
      {products.map((p, i) => <Tile key={p.id} p={p} big={feature && i % 7 === 0} />)}
    </Reveal>
  )
}
