import { Link } from 'react-router-dom'
import { useStore } from '../useStore'

export default function Footer() {
  const { config } = useStore()
  return (
    <footer className="foot">
      <div className="card">
        <svg className="scallops" viewBox="0 0 1200 50" preserveAspectRatio="none" aria-hidden="true">
          <path d={'M0 50' + Array.from({ length: 12 }, (_, i) => ` A50 50 0 0 1 ${(i + 1) * 100} 50`).join('') + ' Z'} />
        </svg>
        <div className="card-left">
          <p className="card-sign">See you at the haat.</p>
          <p>{config?.footer_line}</p>
        </div>
        <div className="card-right">
          {config?.stamp && <img className="stamp" src={config.stamp} alt="" width="88" height="117" loading="lazy" />}
          <ul className="card-links">
            <li><Link to="/shop">Every product</Link></li>
            <li><Link to="/cart">Your cart</Link></li>
            <li><Link to="/orders">Your orders</Link></li>
          </ul>
        </div>
        <p className="imprint">Haat MVP. Product photos and listings from daraz.com.bd, for demo only.</p>
      </div>
    </footer>
  )
}
