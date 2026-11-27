export default function EmptyState({ icon, title, children, action }) {
  return (
    <div className="grid justify-items-center gap-3.5 px-gutter py-[clamp(48px,10vw,120px)] text-center">
      <span className="mb-1 grid size-18 place-items-center rounded-full bg-muted text-[2rem] text-muted-foreground" aria-hidden="true">{icon}</span>
      <h1>{title}</h1>
      {children && <p className="max-w-[44ch] text-muted-foreground">{children}</p>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  )
}
