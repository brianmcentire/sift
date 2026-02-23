import { useState } from 'react'

export default function HashCell({ hash }) {
  const [expanded, setExpanded] = useState(false)

  if (!hash) return <span className="text-slate-300">—</span>

  return (
    <button
      onClick={() => setExpanded(e => !e)}
      title={expanded ? 'Click to collapse' : 'Click to expand'}
      className="font-mono text-[11px] text-slate-400 hover:text-slate-700 transition-colors duration-150 text-left cursor-pointer"
    >
      {expanded ? hash : `${hash.slice(0, 8)}···`}
    </button>
  )
}
