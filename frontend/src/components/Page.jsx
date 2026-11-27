import { cn } from 'cn'

// The site column. A Page inside a Page (a loading skeleton in a section) adds no extra margin or padding.
export default function Page({ as: Tag = 'section', className, ...rest }) {
  return (
    <Tag data-slot="page" className={cn('mx-auto my-[clamp(32px,5vw,64px)] w-full max-w-site px-gutter in-data-[slot=page]:m-0 in-data-[slot=page]:p-0', className)} {...rest} />
  )
}
