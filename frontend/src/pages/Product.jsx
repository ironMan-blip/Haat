import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useFetch } from '../api'
import Comments from '../components/Comments'
import Qty from '../components/Qty'
import Rating from '../components/Rating'
import Status from '../components/Status'
import TileGrid from '../components/TileGrid'
import { useStore } from '../useStore'

const ZOOM = 2.5 // must match background-size in .pdp-zoom

// Places the lens over the image and pans the side pane to the same spot, via CSS vars.
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

  return (
    <Status loading={loading} error={error}>
      {p && (
        <>
          <section className="page pdp">
            <nav className="crumbs" aria-label="Breadcrumb">
              <Link to="/">Home</Link><span aria-hidden="true">/</span>
              <Link to={`/shop?category=${p.category.slug}`}>{p.category.name}</Link>
            </nav>
            <div className="pdp-media">
              <div
                className="pdp-pic"
                onMouseMove={(e) => moveZoom(e.currentTarget, e.clientX, e.clientY)}
              >
                <img src={p.gallery[shown].image_large} alt={p.gallery[shown].alt} width="800" height="800" />
                <span className="pdp-lens" aria-hidden="true" />
                <div className="pdp-zoom" aria-hidden="true" style={{ backgroundImage: `url(${p.gallery[shown].image_large})` }} />
              </div>
              {p.gallery.length > 1 && (
                <div className="pdp-thumbs">
                  {p.gallery.map((g, i) => (
                    <button key={i} type="button" aria-label={g.alt} aria-pressed={i === shown} onClick={() => setShown(i)}>
                      <img src={g.thumb} alt="" width="200" height="200" />
                    </button>
                  ))}
                </div>
              )}
            </div>
            <div className="pdp-info">
              <Link to={`/shop?category=${p.category.slug}`} className="pdp-cat">{p.category.name}</Link>
              <h1>{p.name}</h1>
              <Rating p={p} />
              <p className="pdp-price">
                {p.price_display}
                {p.original_price_display && <> <s>{p.original_price_display}</s> <span className="off">{p.discount_label}</span></>}
              </p>
              {p.stock_level !== 'out' ? (
                <>
                  <p className={p.stock_level === 'low' ? 'stock stock--low' : 'stock'}>{p.stock_label}</p>
                  <div className="pdp-buy">
                    <Qty value={qty} max={p.max_qty} onChange={setQty} label="Quantity" />
                    <button className="btn" onClick={() => add(p, qty)}>Add to cart</button>
                    <button className="btn btn--line" onClick={() => add(p, qty).then((ok) => ok && navigate('/cart'))}>Buy now</button>
                  </div>
                  <ul className="perks">
                    {config?.perks.map((t) => <li key={t}>{t}</li>)}
                  </ul>
                </>
              ) : (
                <p className="stock stock--out">{p.stock_label}</p>
              )}
              {p.specs.length > 0 && (
                <ul className="pdp-spec">
                  {p.specs.map((line, i) => <li key={i}>{line}</li>)}
                </ul>
              )}
            </div>
          </section>
          <Comments slug={slug} />
          {p.related.length > 0 && (
            <section className="page">
              <div className="sec-head"><h2>More in {p.category.name}</h2></div>
              <TileGrid products={p.related} />
            </section>
          )}
        </>
      )}
    </Status>
  )
}
