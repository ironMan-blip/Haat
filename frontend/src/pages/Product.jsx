import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { discount, img, taka } from '../api'
import { Qty, Rating, Status, TileGrid, useFetch } from '../components'
import { useStore } from '../store'

export default function Product() {
  const { slug } = useParams()
  const { data: p, loading, error } = useFetch(`/products/${slug}/`)
  const related = useFetch(p && `/products/?category=${p.category.slug}`)
  const { add, config } = useStore()
  const navigate = useNavigate()
  const [qty, setQty] = useState(1)

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
                {discount(p) > 0 && <> <s>{taka(p.original_price)}</s> <span className="off">{discount(p)}% off</span></>}
              </p>
              {p.stock > 0 ? (
                <>
                  <p className={p.stock < 10 ? 'stock stock--low' : 'stock'}>{p.stock < 10 ? `Only ${p.stock} left` : 'In stock'}</p>
                  <div className="pdp-buy">
                    <Qty value={qty} max={Math.min(p.stock, 20)} onChange={setQty} label="Quantity" />
                    <button className="btn" onClick={() => add(p, qty)}>Add to cart</button>
                    <button className="btn btn--line" onClick={() => { add(p, qty); navigate('/cart') }}>Buy now</button>
                  </div>
                  <ul className="perks">
                    <li>Cash on delivery, pay when it arrives</li>
                    <li>Free delivery on orders over {taka(config.free_delivery_min)}</li>
                  </ul>
                </>
              ) : (
                <p className="stock stock--out">Sold out</p>
              )}
              {p.description && (
                <ul className="pdp-spec">
                  {p.description.split('\n').map((line, i) => <li key={i}>{line}</li>)}
                </ul>
              )}
            </div>
          </section>
          {related.data?.length > 1 && (
            <section className="page">
              <div className="sec-head"><h2>More in {p.category.name}</h2></div>
              <TileGrid products={related.data.filter((r) => r.id !== p.id).slice(0, 7)} />
            </section>
          )}
        </>
      )}
    </Status>
  )
}
