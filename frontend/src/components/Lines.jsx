import { Link } from 'react-router-dom'
import { cn } from 'cn'

// Cart and order item rows: thumbnail, name, detail lines; cart rows add their controls as children.
export function Lines({ className, ...rest }) {
  return <ul className={cn('grid gap-3', className)} {...rest} />
}

export function Line({ thumb, size = 72, slug, name, details, children, className }) {
  return (
    <li className={cn('grid items-center gap-5', className)}>
      <img src={thumb} alt="" width={size} height={size} loading="lazy" className="aspect-square w-full rounded-lg bg-page object-contain mix-blend-multiply" />
      <div className="grid min-w-0 gap-0.5">
        <Link to={`/p/${slug}`} className="truncate font-semibold no-underline hover:text-primary">{name}</Link>
        {details.filter(Boolean).map((d, i) => <span key={i} className="text-muted-foreground">{d}</span>)}
      </div>
      {children}
    </li>
  )
}
