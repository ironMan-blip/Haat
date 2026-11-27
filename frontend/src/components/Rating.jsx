export default function Rating({ p }) {
  if (!p.rating_label) return null
  return (
    <span className="inline-flex items-center gap-1 text-small text-muted-foreground before:text-star before:content-['★']" aria-label={p.rating_label}>
      <b className="font-semibold text-foreground">{p.rating}</b> ({p.reviews_display})
    </span>
  )
}
