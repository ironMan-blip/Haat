import { Link } from 'react-router-dom'
import { useFetch } from '../api'
import Reveal from '../components/Reveal'
import Status from '../components/Status'
import TileGrid from '../components/TileGrid'
import { useStore } from '../useStore'

// Brickwork wall of goods and price tags, like a haat laid out on the ground.
function Wall({ rows }) {
  return (
    <div className="wall" aria-hidden="true">
      {rows.map((row, r) => (
        <div className="wall-row" key={r}>
          {row.map((b, c) =>
            b.tag ? (
              <span key={c} className={`wall-tile tag ${b.field}`}>{b.tag}</span>
            ) : (
              <span key={c} className="wall-tile"><img src={b.image} alt="" width="112" height="112" /></span>
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
          <img className="panel-pic" src={p.image_large} alt={p.name} loading="lazy" width="800" height="800" />
          <div className="panel-row">
            <div>
              <Link to={`/p/${p.slug}`} className="panel-name">{p.panel_name}</Link>
              <p className="panel-fact">{p.panel_fact}</p>
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
            <span>{cat.count_label}</span>
          </div>
          <ul className="menu-items">
            {cat.items.map((p) => (
              <li key={p.id}>
                <Link to={`/p/${p.slug}`} className="menu-item">
                  <img src={p.thumb} alt="" width="64" height="64" loading="lazy" />
                  <span className="menu-text">
                    <span className="menu-line"><b>{p.name}</b><span>{p.price_display}</span></span>
                    <span className="menu-desc">{p.summary}</span>
                    {p.note && <span className="menu-note">{p.note}</span>}
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
  const { wall = [], deals = [], best = [], menu = [], hero, promise } = data || {}

  return (
    <Status loading={loading} error={error}>
      {wall.length > 0 && (
        <section className="hero">
          <Wall rows={wall} />
          <div className="dock">
            <div>
              <h1 className="dock-head">{hero.head}</h1>
              <p className="dock-line">{hero.line}</p>
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

      {promise && (
        <section className="promise">
          <Reveal as="p" className="promise-line">{promise}</Reveal>
        </section>
      )}

      <Menu menu={menu} />
    </Status>
  )
}
