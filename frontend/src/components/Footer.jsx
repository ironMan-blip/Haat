import { Link } from 'react-router-dom'
import { useStore } from '../useStore'

const link = 'no-underline hover:text-white hover:underline'

export default function Footer() {
  const { config } = useStore()
  return (
    <footer className="mt-[clamp(64px,8vw,120px)] bg-foreground px-gutter pb-8 text-paper">
      <div className="mx-auto grid max-w-7xl gap-10 pt-14 md:grid-cols-[2fr_1fr]">
        <div>
          <p className="mb-3 text-2xl font-bold tracking-[-0.02em] text-white">See you at the haat.</p>
          <p className="max-w-[46ch]">{config?.footer_line}</p>
        </div>
        <ul className="grid gap-2.5">
          <li><Link className={link} to="/shop">Every product</Link></li>
          <li><Link className={link} to="/cart">Your cart</Link></li>
          <li><Link className={link} to="/orders">Your orders</Link></li>
        </ul>
        <p className="col-span-full border-t border-white/12 pt-6 text-small text-[#9a968d]">Haat MVP. Product photos and listings from daraz.com.bd, for demo only.</p>
      </div>
    </footer>
  )
}
