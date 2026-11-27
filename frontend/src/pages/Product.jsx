import { useState } from 'react'
import { Check } from 'lucide-react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useFetch } from '../api'
import { cn } from 'cn'
import Comments from '../components/Comments'
import Page from '../components/Page'
import Qty from '../components/Qty'
import Rating from '../components/Rating'
import Status from '../components/Status'
import TileGrid from '../components/TileGrid'
import { Breadcrumb, BreadcrumbItem, BreadcrumbLink, BreadcrumbList, BreadcrumbSeparator } from '../components/ui/breadcrumb'
import { Button } from '../components/ui/button'
import { useStore } from '../useStore'

const ZOOM = 2.5 // must match bg-size-[250%] on the zoom pane

// Places the lens over the image and pans the side pane to the same spot, via CSS vars the classes read.
function moveZoom(box, x, y) {
  const img = box.querySelector('img')
  const r = img.getBoundingClientRect()
  const h = 1 / (2 * ZOOM) // half the lens, as a fraction of the image
  const cx = Math.min(Math.max((x - r.left) / r.width, h), 1 - h)
  const cy = Math.min(Math.max((y - r.top) / r.height, h), 1 - h)
  const s = box.style
  s.setProperty('--lw', `${r.width / ZOOM}px`)
  s.setProperty('--lx', `${img.offsetLeft + (cx - h) * r.width}px`)
  s.setProperty('--ly', `${img.offsetTop + (cy - h) * r.height}px`)
  s.setProperty('--bx', `${((cx - h) * ZOOM * 100) / (ZOOM - 1)}%`)
  s.setProperty('--by', `${((cy - h) * ZOOM * 100) / (ZOOM - 1)}%`)
}

// Keyed by slug so moving to a related product starts fresh (quantity back to 1).
const stock = {
  in: 'text-foreground before:bg-primary',
  low: 'text-warn before:bg-warn',
  out: 'text-destructive before:bg-destructive',
}
const Stock = ({ item }) => (
  <p className={cn('inline-flex items-center gap-2 font-medium before:size-2 before:rounded-full', stock[item.stock_level] ?? stock.in)}>{item.stock_label}</p>
)
const crumb = 'no-underline hover:text-primary hover:underline'

export default function Product() {
  const { slug } = useParams()
  return <ProductPage key={slug} slug={slug} />
}

function ProductPage({ slug }) {
  const { data: p, loading, error } = useFetch(`/products/${slug}/`)
  const { add, config } = useStore()
  const navigate = useNavigate()
  const [qty, setQty] = useState(1) // Qty stops at max_qty; the server caps it again
  const [shown, setShown] = useState(0) // index into p.gallery
  const [chosen, setChosen] = useState({}) // {Size: 'M'}; the server says what is still missing
  // Once every option is picked, that combination's price and stock replace the product's.
  const picked = p?.variants.find((x) => p.options.every((o) => x.choices[o.name] === chosen[o.name]))
  const item = picked ?? p
  const n = Math.min(qty, item?.max_qty ?? qty) // a smaller combination may hold less than was set

  return (
    <Status loading={loading} error={error}>
      {p && (
        <>
          <Page className="grid items-start gap-[clamp(24px,4vw,64px)] md:grid-cols-[7fr_5fr]">
            <Breadcrumb className="col-span-full">
              <BreadcrumbList className="gap-2 text-small">
                <BreadcrumbItem><BreadcrumbLink asChild className={crumb}><Link to="/">Home</Link></BreadcrumbLink></BreadcrumbItem>
                <BreadcrumbSeparator className="text-border">/</BreadcrumbSeparator>
                <BreadcrumbItem><BreadcrumbLink asChild className={crumb}><Link to={`/shop?category=${p.category.slug}`}>{p.category.name}</Link></BreadcrumbLink></BreadcrumbItem>
              </BreadcrumbList>
            </Breadcrumb>
            <div className="z-2 grid gap-3 md:sticky md:top-22">
              <div
                className="group/pic relative grid aspect-square place-items-center rounded-2xl border bg-background md:pointer-fine:cursor-crosshair"
                onMouseMove={(e) => moveZoom(e.currentTarget, e.clientX, e.clientY)}
              >
                <img className="aspect-square w-[86%] object-contain mix-blend-multiply" src={p.gallery[shown].image_large} alt={p.gallery[shown].alt} width="800" height="800" />
                {/* Side zoom: lens on the image, magnified pane over the info column. Mouse + wide screens only. */}
                <span className="pointer-events-none absolute top-(--ly) left-(--lx) hidden aspect-square w-(--lw) rounded-lg border border-primary bg-primary/12 md:group-hover/pic:block" aria-hidden="true" />
                <div className="pointer-events-none absolute -top-px left-[calc(100%+clamp(24px,4vw,64px))] hidden aspect-square w-[72%] rounded-2xl border bg-background bg-size-[250%] bg-[position:var(--bx)_var(--by)] bg-no-repeat shadow-float md:group-hover/pic:block"
                  aria-hidden="true" style={{ backgroundImage: `url(${p.gallery[shown].image_large})` }} />
              </div>
              {p.gallery.length > 1 && (
                <div className="flex gap-2 overflow-x-auto">
                  {p.gallery.map((g, i) => (
                    <button key={i} type="button" aria-label={g.alt} aria-pressed={i === shown} onClick={() => setShown(i)}
                      className="aspect-square flex-[0_0_72px] rounded-lg border bg-background p-1 aria-pressed:border-primary aria-pressed:ring-1 aria-pressed:ring-primary">
                      <img className="size-full object-contain mix-blend-multiply" src={g.thumb} alt="" width="200" height="200" />
                    </button>
                  ))}
                </div>
              )}
            </div>
            <div className="grid min-w-0 gap-4">
              <Link to={`/shop?category=${p.category.slug}`} className="justify-self-start text-small font-semibold text-primary no-underline hover:underline">{p.category.name}</Link>
              <h1 className="text-[clamp(1.25rem,1rem+1.2vw,2rem)] leading-[1.25]">{p.name}</h1>
              <Rating p={p} />
              <p className="flex flex-wrap items-baseline gap-x-3 gap-y-1 border-y py-4 text-[clamp(2rem,1.6rem+1.4vw,2.75rem)] leading-none font-bold tracking-[-0.03em]">
                {item.price_display}
                {item.original_price_display && <> <s className="text-base tracking-normal">{item.original_price_display}</s> <span className="rounded-md bg-sale-soft px-2 py-0.75 text-base font-semibold tracking-normal whitespace-nowrap text-destructive">{item.discount_label}</span></>}
              </p>
              {p.stock_level !== 'out' && p.options.map((o) => (
                <fieldset key={o.name} className="flex flex-wrap gap-2">
                  <legend className="mb-2 font-semibold">{o.name}{chosen[o.name] && <span className="text-muted-foreground">: {chosen[o.name]}</span>}</legend>
                  {o.values.map((v) => (
                    <Button key={v} type="button" variant="outline" aria-pressed={chosen[o.name] === v}
                      className="h-10 min-w-12 px-3.5 font-normal hover:border-primary hover:bg-background aria-pressed:border-primary aria-pressed:font-semibold aria-pressed:ring-1 aria-pressed:ring-primary"
                      onClick={() => setChosen({ ...chosen, [o.name]: v })}>{v}</Button>
                  ))}
                </fieldset>
              ))}
              {item.stock_level !== 'out' ? (
                <>
                  <Stock item={item} />
                  {/* Phones: the buy row stays pinned to the screen bottom while the details scroll. */}
                  <div className="flex flex-wrap items-center gap-2.5 max-md:sticky max-md:z-10 max-md:bottom-0 max-md:-mx-gutter max-md:flex-nowrap max-md:bg-background max-md:px-gutter max-md:py-3 max-md:shadow-float">
                    <Qty value={n} max={item.max_qty} onChange={setQty} label="Quantity" />
                    <Button className="h-12.5 min-w-0 flex-1 max-md:px-3" onClick={() => add(p, n, chosen)}>Add to cart</Button>
                    <Button variant="line" className="h-12.5 min-w-0 flex-1 max-md:px-3" onClick={() => add(p, n, chosen).then((ok) => ok && navigate('/cart'))}>Buy now</Button>
                  </div>
                  <ul className="grid gap-2 rounded-xl bg-secondary px-5 py-4 text-small font-medium text-secondary-foreground">
                    {config?.perks.map((t) => <li key={t} className="flex items-start gap-2"><Check aria-hidden="true" strokeWidth={2.5} className="mt-0.5 size-4 flex-none" />{t}</li>)}
                  </ul>
                </>
              ) : (
                <Stock item={item} />
              )}
              {p.specs.length > 0 && (
                <ul className="grid list-disc gap-1.5 rounded-xl border bg-background py-5 pr-5 pl-10">
                  {p.specs.map((line, i) => <li key={i}>{line}</li>)}
                </ul>
              )}
            </div>
          </Page>
          <Comments slug={slug} />
          {p.related.length > 0 && (
            <Page>
              <h2 className="mb-6">{p.related_title}</h2>
              <TileGrid products={p.related} />
            </Page>
          )}
        </>
      )}
    </Status>
  )
}
