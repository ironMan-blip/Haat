// `heading="h2"` when the page above already has its own h1.
export default function EmptyState({ icon, title, children, action, heading: H = 'h1' }) {
  return (
    <div className="grid justify-items-center gap-3.5 px-gutter py-[clamp(48px,10vw,120px)] text-center">
      <span className="mb-1 grid size-18 place-items-center rounded-full bg-muted text-muted-foreground [&_svg]:size-8" aria-hidden="true">{icon}</span>
      <H className="text-h2">{title}</H>
      {children && <p className="max-w-[44ch] text-muted-foreground">{children}</p>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  )
}
