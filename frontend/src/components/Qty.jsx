import { Button } from './ui/button'

const step = 'h-11.5 w-11 text-xl font-normal disabled:cursor-not-allowed disabled:text-[#bbb] disabled:opacity-100'

export default function Qty({ value, max, onChange, label, className }) {
  return (
    <span className={`inline-flex items-center rounded-lg border bg-background ${className ?? ''}`} role="group" aria-label={label}>
      <Button variant="ghost" className={step} type="button" onClick={() => onChange(value - 1)} disabled={value <= 1} aria-label="One less">−</Button>
      <output className="min-w-8 text-center font-semibold" aria-live="polite">{value}</output>
      <Button variant="ghost" className={step} type="button" onClick={() => onChange(value + 1)} disabled={value >= max} aria-label="One more">+</Button>
    </span>
  )
}
