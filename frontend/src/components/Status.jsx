import EmptyState from './EmptyState'
import Page from './Page'
import { Grid } from './TileGrid'
import { Button } from './ui/button'
import { Skeleton } from './ui/skeleton'

function Loading({ n = 8 }) {
  return (
    <Grid aria-busy="true" aria-label="Loading">
      {Array.from({ length: n }, (_, i) => (
        <div className="grid gap-2.5" key={i}>
          <Skeleton className="aspect-square rounded-xl" />
          <Skeleton className="h-3.5" />
          <Skeleton className="h-3.5 w-2/5" />
        </div>
      ))}
    </Grid>
  )
}

export default function Status({ loading, error, children }) {
  if (loading) return <Page as="div"><Loading /></Page>
  if (error)
    return (
      <EmptyState icon="!" title="We couldn't load this page"
        action={<Button onClick={() => location.reload()}>Try again</Button>}>
        Check your connection and try again. ({error.message})
      </EmptyState>
    )
  return children
}
