import { useEffect, useRef } from 'react'
import { cn } from 'cn'

// Children rise in sequence when the element scrolls into view. Hidden only once JS has armed it, so content stays visible without JS.
const rise = cn(
  '*:transition-[opacity,translate,box-shadow,border-color] *:duration-500 *:ease-haat',
  'not-data-in:data-armed:*:translate-y-4 not-data-in:data-armed:*:opacity-0 motion-reduce:*:translate-y-0!',
  'data-in:*:nth-2:delay-50 data-in:*:nth-3:delay-100 data-in:*:nth-4:delay-150 data-in:*:nth-[n+5]:delay-200 data-in:*:hover:delay-0',
)

export default function Reveal({ as: Tag = 'div', className, children, ...rest }) {
  const ref = useRef(null)
  useEffect(() => {
    const el = ref.current
    if (!el || !('IntersectionObserver' in window)) return
    el.dataset.armed = ''
    const io = new IntersectionObserver(([e]) => {
      if (e.isIntersecting) { el.dataset.in = ''; io.disconnect() }
    }, { rootMargin: '0px 0px -10% 0px' })
    io.observe(el)
    return () => io.disconnect()
  }, [])
  return <Tag ref={ref} className={cn(rise, className)} {...rest}>{children}</Tag>
}
