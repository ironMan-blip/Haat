import EmptyState from './EmptyState'

function Skeleton({ n = 8 }) {
  return (
    <div className="tiles" aria-busy="true" aria-label="Loading">
      {Array.from({ length: n }, (_, i) => (
        <div className="skel-tile" key={i}>
          <span className="skel skel-pic" />
          <span className="skel skel-line" />
          <span className="skel skel-line short" />
        </div>
      ))}
    </div>
  )
}

export default function Status({ loading, error, children }) {
  if (loading) return <div className="page"><Skeleton /></div>
  if (error)
    return (
      <EmptyState icon="!" title="We couldn't load this page"
        action={<button className="btn" onClick={() => location.reload()}>Try again</button>}>
        Check your connection and try again. ({error.message})
      </EmptyState>
    )
  return children
}
