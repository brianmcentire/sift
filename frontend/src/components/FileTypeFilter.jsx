import { useState, useRef, useEffect } from 'react'

const CATEGORY_LABELS = {
  image: '🖼 Images',
  video: '🎬 Video',
  audio: '🎵 Audio',
  document: '📄 Docs',
  code: '💻 Code',
  archive: '📦 Archives',
  other: '📎 Other',
}

// value: Set<string>, onChange: (Set<string>) => void
export default function FileTypeFilter({ value, onChange, categories }) {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)

  useEffect(() => {
    if (!open) return
    function handler(e) {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  function toggle(cat) {
    const next = new Set(value)
    if (next.has(cat)) next.delete(cat)
    else next.add(cat)
    onChange(next)
  }

  const label = value.size === 0
    ? 'All types'
    : value.size === 1
      ? (CATEGORY_LABELS[[...value][0]] || [...value][0])
      : `${value.size} types`

  return (
    <div className="relative shrink-0" ref={ref}>
      <button
        onClick={() => categories.length > 0 && setOpen(o => !o)}
        className={`
          text-sm px-2.5 py-1.5
          bg-white border rounded-lg
          focus:outline-none focus:ring-2 focus:ring-blue-400
          transition-all duration-150 whitespace-nowrap
          ${categories.length === 0 ? 'opacity-40 cursor-default' : 'cursor-pointer'}
          ${value.size > 0 ? 'border-blue-300 text-blue-600' : 'border-slate-200 text-slate-600'}
        `}
      >
        {label}
      </button>

      {open && (
        <div className="absolute right-0 top-full mt-1 z-50 bg-white border border-slate-200 rounded-lg shadow-lg p-2 min-w-[160px]">
          {categories.map(cat => (
            <label
              key={cat}
              className="flex items-center gap-2 px-2 py-1.5 rounded-md hover:bg-slate-50 cursor-pointer text-sm text-slate-700 select-none"
            >
              <input
                type="checkbox"
                checked={value.has(cat)}
                onChange={() => toggle(cat)}
                className="accent-blue-600"
              />
              {CATEGORY_LABELS[cat] || cat}
            </label>
          ))}
          {value.size > 0 && (
            <button
              onClick={() => onChange(new Set())}
              className="w-full mt-1 pt-1.5 border-t border-slate-100 text-[11px] text-slate-400 hover:text-slate-600 text-center"
            >
              Clear
            </button>
          )}
        </div>
      )}
    </div>
  )
}
