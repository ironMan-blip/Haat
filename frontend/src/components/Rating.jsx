export default function Rating({ p }) {
  if (!p.rating_label) return null
  return <span className="rating" aria-label={p.rating_label}><b>{p.rating}</b> ({p.reviews_display})</span>
}
