import { Link } from 'react-router-dom'
import { useStore } from '../useStore'

export default function Toast() {
  const { notice } = useStore()
  if (!notice) return null
  return (
    <div className="fixed bottom-4 left-1/2 z-30 flex max-w-[calc(100%-32px)] -translate-x-1/2 items-center gap-4 rounded-xl bg-foreground py-3 pr-3 pl-4.5 text-background shadow-float animate-in fade-in slide-in-from-bottom-3 duration-240 md:bottom-6 motion-reduce:animate-none"
      role="status" key={notice.at}>
      <p className="truncate">{notice.text}</p>
      {notice.link && <Link to="/cart" className="flex-none rounded-lg px-2.5 py-2 font-semibold text-[#9fe0bf] no-underline hover:bg-white/10">View cart</Link>}
    </div>
  )
}
