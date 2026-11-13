import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { img, taka, useFetch } from '../api'
import { Qty, Rating, Status, TileGrid } from '../components'
import { useStore } from '../store'

// Keyed by slug so moving to a related product starts fresh (quantity back to 1).
export default function Product() {
  const { slug } = useParams()
  return <ProductPage key={slug} slug={slug} />
}

function ProductPage({ slug }) {
  const { data: p, loading, error } = useFetch(`/products/${slug}/`)
  const { add, config } = useStore()
  const navigate = useNavigate()
  const [pick, setQty] = useState(1)
  const qty = Math.max(1, Math.min(pick, p?.max_qty ?? 1))

  return (
    <Status loading={loading} error={error}>
      {p && (
        <>
          <section className="page pdp">
            <nav className="crumbs" aria-label="Breadcrumb">
              <Link to="/">Home</Link><span aria-hidden="true">/</span>
              <Link to={`/shop?category=${p.category.slug}`}>{p.category.name}</Link>
            </nav>
            <div className="pdp-pic">
              <img src={img(p.image, 800)} alt={p.name} width="800" height="800" />
            </div>
            <div className="pdp-info">
              <Link to={`/shop?category=${p.category.slug}`} className="pdp-cat">{p.category.name}</Link>
              <h1>{p.name}</h1>
              {p.reviews > 0 && <Rating p={p} />}
              <p className="pdp-price">
                {taka(p.price)}
                {p.discount > 0 && <> <s>{taka(p.original_price)}</s> <span className="off">{p.discount}% off</span></>}
              </p>
              {p.stock_level !== 'out' ? (
                <>
                  <p className={p.stock_level === 'low' ? 'stock stock--low' : 'stock'}>{p.stock_level === 'low' ? `Only ${p.stock} left` : 'In stock'}</p>
                  <div className="pdp-buy">
                    <Qty value={qty} max={p.max_qty} onChange={setQty} label="Quantity" />
                    <button className="btn" onClick={() => add(p, qty)}>Add to cart</button>
                    <button className="btn btn--line" onClick={() => add(p, qty).then((ok) => ok && navigate('/cart'))}>Buy now</button>
                  </div>
                  <ul className="perks">
                    <li>Cash on delivery, pay when it arrives</li>
                    {config && <li>Free delivery on orders over {taka(config.free_delivery_min)}</li>}
                  </ul>
                </>
              ) : (
                <p className="stock stock--out">Sold out</p>
              )}
              {p.specs.length > 0 && (
                <ul className="pdp-spec">
                  {p.specs.map((line, i) => <li key={i}>{line}</li>)}
                </ul>
              )}
            </div>
          </section>
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
