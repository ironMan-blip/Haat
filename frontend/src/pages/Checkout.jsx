import { useState } from 'react'
import { Link, Navigate, useNavigate } from 'react-router-dom'
import { api } from '../api'
import Fail from '../components/Fail'
import Page from '../components/Page'
import Status from '../components/Status'
import Summary from '../components/Summary'
import { Button } from '../components/ui/button'
import { Input } from '../components/ui/input'
import { Label } from '../components/ui/label'
import { NativeSelect, NativeSelectOption } from '../components/ui/native-select'
import { RadioGroup, RadioGroupItem } from '../components/ui/radio-group'
import { Textarea } from '../components/ui/textarea'
import { cn } from 'cn'
import { checkoutGrid, checkoutHead, formCard, hint, textLink } from '../lib/styles'
import { useStore } from '../useStore'

export default function Checkout() {
  const { auth, cart, config, reloadCart, expire } = useStore()
  const navigate = useNavigate()
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [placed, setPlaced] = useState(false)

  if (cart && !cart.lines.length && !placed) return <Navigate to="/cart" replace />
  if (!cart) return <Status loading />
  const t = config.text.checkout

  const submit = async (e) => {
    e.preventDefault()
    setBusy(true)
    setError('')
    const form = Object.fromEntries(new FormData(e.currentTarget))
    try {
      // The server builds the order from the session cart and empties it; it refuses if the
      // cart no longer matches the total shown here.
      // No token places a guest order: the server keeps it on this browser's session.
      const order = await api('/orders/', { method: 'POST', token: auth?.token, body: { ...form, expected_total: cart.total } })
      setPlaced(true) // keeps the empty-cart guard from redirecting to /cart
      reloadCart()
      // Router state, not a URL param, so a crafted link can't show a fake confirmation.
      navigate('/orders', { state: { notice: order.notice } })
    } catch (err) {
      setError(err.message)
      setBusy(false)
      // Stale token: forget it and let them choose; never retry as a guest, or the order misses their account.
      if (err.status === 401) expire()
      else reloadCart() // show the cart the server has now
    }
  }

  return (
    <Page className={checkoutGrid}>
      <form className={cn(formCard, 'max-w-none')} onSubmit={submit}>
        <Link to="/cart" className={cn(textLink, 'justify-self-start text-small')}>{t.back}</Link>
        <h1 className={checkoutHead}>{t.title}</h1>
        {!auth && <p className="text-muted-foreground">{t.guest} <Link to="/login?next=/checkout" className={textLink}>{t.guest_login}</Link> {t.guest_after}</p>}
        <Label>{t.name}<Input className="font-normal" name="full_name" required autoComplete="name" /></Label>
        <Label>{t.phone}
          <Input className="font-normal" name="phone" type="tel" required placeholder={t.phone_placeholder} autoComplete="tel" />
          <span className={hint}>{t.phone_hint}</span>
        </Label>
        {!auth && (
          <Label>{t.email}
            <Input className="font-normal" name="email" type="email" autoComplete="email" />
            <span className={hint}>{t.email_hint}</span>
          </Label>
        )}
        <Label>{t.city}
          <NativeSelect className="w-full font-normal" name="city" required>
            {config.cities.map((c) => <NativeSelectOption key={c}>{c}</NativeSelectOption>)}
          </NativeSelect>
        </Label>
        <Label>{t.address}<Textarea className="resize-y font-normal" name="address" required rows={3} placeholder={t.address_placeholder} autoComplete="street-address" /></Label>
        <fieldset>
          <legend className="mb-2 text-[0.9375rem] font-semibold">{t.payment}</legend>
          <RadioGroup name="payment" defaultValue={config.payments[0]?.value}>
            {config.payments.map((m) => (
              <Label key={m.value} className="flex items-center gap-3 rounded-lg border bg-background px-4 py-3.5 font-medium transition-colors hover:border-primary has-data-[state=checked]:border-primary has-data-[state=checked]:bg-secondary">
                <RadioGroupItem value={m.value} className="size-5" /> {m.label} {m.hint && <span className={hint}>{m.hint}</span>}
              </Label>
            ))}
          </RadioGroup>
        </fieldset>
        {error && <Fail>{error}</Fail>}
        <Button className="w-full" disabled={busy}>{busy ? t.busy : t.submit}</Button>
      </form>
      <Summary lines />
    </Page>
  )
}
