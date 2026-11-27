import { Alert } from './ui/alert'

// A refused request's message, shown in place.
export default function Fail({ children }) {
  return <Alert variant="destructive" className="border-0 bg-sale-soft px-4 py-3 text-base font-medium">{children}</Alert>
}
