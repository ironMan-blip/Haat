import { Link } from 'react-router-dom'
import { useStore } from '../useStore'

export default function Toast() {
  const { notice } = useStore()
  if (!notice) return null
  return (
    <div className="toast" role="status" key={notice.at}>
      <p>{notice.text}</p>
      {notice.link && <Link to="/cart">View cart</Link>}
    </div>
  )
}
