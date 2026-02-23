import { useState, useRef, useEffect } from 'react'

const COLUMNS = [
  { key: 'size', label: 'Size' },
  { key: 'date', label: 'Modified' },
  { key: 'seen', label: 'Last Seen' },
  { key: 'type', label: 'Type' },
  { key: 'hash', label: 'Hash' },
  { key: 'hosts', label: 'Hosts' },
]

export default function ColumnToggle({ visibleColumns, setVisibleColumns }) {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)

  useEffect(() => {
    function handle(e) {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false)
    }
    document.addEventListener('mousedown', handle)
    return () => document.removeEventListener('mousedown', handle)
  }, [])

  function toggle(key) {
    setVisibleColumns(prev => ({ ...prev, [key]: !prev[key] }))
  }

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen(o => !o)}
        title="Toggle columns"
        className="
          flex items-center gap-1 px-2.5 py-1.5 text-sm
          border border-slate-200 rounded-lg bg-white
          text-slate-600 hover:bg-slate-50 cursor-pointer
          transition-all duration-150
        "
      >
        <span className="text-base">⊞</span>
        <span className="text-[11px] text-slate-400 hidden sm:block">cols</span>
      </button>

      {open && (
        <div className="
          absolute right-0 top-full mt-1 z-50
          bg-white border border-slate-200 rounded-xl shadow-lg
          py-2 px-1 min-w-[120px]
        ">
          {COLUMNS.map(col => (
            <label
              key={col.key}
              className="flex items-center gap-2 px-3 py-1.5 cursor-pointer rounded-lg hover:bg-slate-50"
            >
              <input
                type="checkbox"
                checked={visibleColumns[col.key]}
                onChange={() => toggle(col.key)}
                className="accent-blue-600 cursor-pointer"
              />
              <span className="text-sm text-slate-700">{col.label}</span>
            </label>
          ))}
        </div>
      )}
    </div>
  )
}
