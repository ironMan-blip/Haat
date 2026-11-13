export default function EmptyState({ icon, title, children, action }) {
  return (
    <div className="state">
      <span className="state-icon" aria-hidden="true">{icon}</span>
      <h1>{title}</h1>
      {children && <p>{children}</p>}
      {action}
    </div>
  )
}
