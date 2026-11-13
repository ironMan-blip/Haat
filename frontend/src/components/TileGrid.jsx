import { Link } from 'react-router-dom'
import { useStore } from '../useStore'
import { PlusIcon } from './icons'
import Rating from './Rating'
import Reveal from './Reveal'

// The name link stretches over the whole tile (CSS ::after); the add button sits above it.
function Tile({ p, big }) {
  const { add } = useStore()
  const out = p.stock_level === 'out'
  return (
    <article className={`tile${big ? ' tile--big' : ''}${out ? ' tile--out' : ''}`}>
      <span className="tile-pic">
        <img src={p.image} alt="" loading="lazy" width="400" height="400" />
        {p.badge && <span className={out ? 'badge badge--out' : 'badge'}>{p.badge}</span>}
      </span>
      <Link to={`/p/${p.slug}`} className="tile-name">{p.name}</Link>
      <Rating p={p} />
      <span className="tile-foot">
        <span className="tile-price">
          {p.price_display}
          {p.original_price_display && <> <s>{p.original_price_display}</s></>}
        </span>
        {!out && (
          <button type="button" className="tile-add" onClick={() => add(p)} aria-label={`Add ${p.name} to cart`}>
            <PlusIcon />
          </button>
        )}
      </span>
    </article>
  )
}

// `feature` enlarges every 7th tile: for short curated rows, not for long lists people scan.
export default function TileGrid({ products, feature }) {
  return (
    <Reveal className="tiles">
      {products.map((p, i) => <Tile key={p.id} p={p} big={feature && i % 7 === 0} />)}
    </Reveal>
  )
}
