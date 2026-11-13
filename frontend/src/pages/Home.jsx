import { Link } from 'react-router-dom'
import { img, taka, useFetch } from '../api'
import { Reveal, Status, TileGrid } from '../components'
import { useStore } from '../store'

const FIELDS = ['f1', 'f2', 'f3']

// Brickwork wall of goods and price tags, like a haat laid out on the ground.
function Wall({ products }) {
  const rows = Array.from({ length: 8 }, (_, r) =>
    Array.from({ length: 16 }, (_, c) => products[(r * 11 + c * 5) % products.length]))
  return (
    <div className="wall" aria-hidden="true">
      {rows.map((row, r) => (
        <div className="wall-row" key={r}>
          {row.map((p, c) =>
            (r + c) % 3 === 0 ? (
              <span key={c} className={`wall-tile tag ${FIELDS[Math.floor(c / 3) % 3]}`}>{taka(p.price)}</span>
            ) : (
              <span key={c} className="wall-tile"><img src={img(p.image, 200)} alt="" width="112" height="112" /></span>
            ))}
        </div>
      ))}
    </div>
  )
}

function Showcase({ items }) {
  const { add } = useStore()
  return (
    <section className="showcase">
      {items.map((p, i) => (
        <Reveal className={i ? 'panel panel--b' : 'panel'} key={p.id}>
          {i === 0 && <h2 className="panel-head">Best rated</h2>}
          <img className="panel-pic" src={img(p.image, 800)} alt={p.name} loading="lazy" width="800" height="800" />
          <div className="panel-row">
            <div>
              <Link to={`/p/${p.slug}`} className="panel-name">{p.name.length > 56 ? `${p.name.slice(0, 54).trimEnd()}…` : p.name}</Link>
              <p className="panel-fact">{taka(p.price)} · rated {p.rating} by {p.reviews.toLocaleString()} buyers</p>
            </div>
            <div className="panel-actions">
              <button className="btn" onClick={() => add(p)}>Add to cart</button>
              <Link className="btn btn--paper" to={`/p/${p.slug}`}>View</Link>
            </div>
          </div>
        </Reveal>
      ))}
    </section>
  )
}

function Menu({ menu }) {
  return (
    <section className="menu page">
      {menu.map((cat) => (
        <Reveal className="menu-cat" key={cat.slug} id={cat.slug}>
          <div className="menu-head">
            <h2><Link to={`/shop?category=${cat.slug}`}>{cat.name}</Link></h2>
            <span>{cat.count} items</span>
          </div>
          <ul className="menu-items">
            {cat.items.map((p) => (
              <li key={p.id}>
                <Link to={`/p/${p.slug}`} className="menu-item">
                  <img src={img(p.image, 200)} alt="" width="64" height="64" loading="lazy" />
                  <span className="menu-text">
                    <span className="menu-line"><b>{p.name}</b><span>{taka(p.price)}</span></span>
                    <span className="menu-desc">{p.summary}</span>
                    {p.discount > 0 && <span className="menu-note">{p.discount}% below the usual {taka(p.original_price)}</span>}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </Reveal>
      ))}
    </section>
  )
}

export default function Home() {
  const { data, loading, error } = useFetch('/home/') // server picks deals, best rated and the menu
  const { config } = useStore()
  const { wall = [], deals = [], best = [], menu = [] } = data || {}

  return (
    <Status loading={loading} error={error}>
      {wall.length > 0 && (
        <section className="hero">
          <Wall products={wall} />
          <div className="dock">
            <div>
              <h1 className="dock-head">Phones to rice, one haat.</h1>
              <p className="dock-line">Pay the rider in cash when it reaches your door.</p>
            </div>
            <Link to="/shop" className="btn">Start shopping</Link>
            <nav className="dock-links" aria-label="Categories">
              {menu.map((c) => <Link key={c.slug} to={`/shop?category=${c.slug}`}>{c.name}</Link>)}
            </nav>
          </div>
        </section>
      )}

      <section className="page">
        <Reveal className="sec-head">
          <h2>Today's best deals</h2>
          <Link to="/shop?sort=price" className="arrow">See all →</Link>
        </Reveal>
        <TileGrid products={deals} feature />
      </section>

      {best.length === 2 && <Showcase items={best} />}

      {config && (
        <section className="promise">
          <Reveal as="p" className="promise-line">
            Spend {taka(config.free_delivery_min)} and delivery is free. Under that it costs {taka(config.delivery_fee)}. You pay the rider in cash at the door.
          </Reveal>
        </section>
      )}

      <Menu menu={menu} />
    </Status>
  )
}
