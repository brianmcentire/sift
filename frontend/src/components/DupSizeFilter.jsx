import { useState, useRef, useEffect } from 'react'

const PRESETS = [
  { label: '0 B',    bytes: 0 },
  { label: '1 KB',   bytes: 1024 },
  { label: '1 MB',   bytes: 1024 ** 2 },
  { label: '100 MB', bytes: 100 * 1024 ** 2 },
  { label: '1 GB',   bytes: 1024 ** 3 },
]

// Parse human size strings: "1.5 MB", "500KB", "2GiB", "1 TiB", etc.
// Returns bytes as integer, or null if unparseable.
function parseSize(str) {
  if (!str || !str.trim()) return null
  const m = str.trim().match(/^(\d+(?:\.\d+)?)\s*([KMGT]i?B|B)?$/i)
  if (!m) return null
  const num = parseFloat(m[1])
  // Normalise: GiB → GB, MiB → MB, etc. (all treated as 1024-based)
  const unit = (m[2] || 'B').toUpperCase().replace(/IB$/, 'B')
  const mult = { B: 1, KB: 1024, MB: 1024 ** 2, GB: 1024 ** 3, TB: 1024 ** 4 }
  if (!(unit in mult)) return null
  return Math.floor(num * mult[unit])
}

function formatBytes(bytes) {
  if (bytes === 0) return '0 B'
  const preset = PRESETS.find(p => p.bytes === bytes)
  if (preset) return preset.label
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let v = bytes, i = 0
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++ }
  return `${v < 10 ? v.toFixed(1) : Math.round(v)} ${units[i]}`
}

// value: number (bytes), onChange: (number) => void
export default function DupSizeFilter({ value, onChange }) {
  const [open, setOpen] = useState(false)
  const [custom, setCustom] = useState('')
  const [customError, setCustomError] = useState(false)
  const ref = useRef(null)

  useEffect(() => {
    if (!open) return
    function handler(e) {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  function applyCustom(str) {
    const bytes = parseSize(str)
    if (bytes === null) { setCustomError(true); return }
    setCustomError(false)
    onChange(bytes)
    setOpen(false)
    setCustom('')
  }

  const isCustom = !PRESETS.some(p => p.bytes === value)

  return (
    <div className="relative shrink-0" ref={ref}>
      <button
        onClick={() => setOpen(o => !o)}
        className={`
          text-sm px-2.5 py-1.5
          bg-white border rounded-lg cursor-pointer
          focus:outline-none focus:ring-2 focus:ring-blue-400
          transition-all duration-150 whitespace-nowrap
          ${value > 0 ? 'border-blue-300 text-blue-600' : 'border-slate-200 text-slate-600'}
        `}
      >
        Min dup size
      </button>

      {open && (
        <div className="absolute right-0 top-full mt-1 z-50 bg-white border border-slate-200 rounded-lg shadow-lg p-3 min-w-[200px]">
          <div className="text-[11px] text-slate-400 mb-2 font-medium uppercase tracking-wide">Min file size</div>

          <div className="flex flex-wrap gap-1.5 mb-3">
            {PRESETS.map(p => (
              <button
                key={p.bytes}
                onClick={() => { onChange(p.bytes); setOpen(false); setCustom('') }}
                className={`
                  px-2 py-1 text-xs rounded-md border transition-colors
                  ${value === p.bytes
                    ? 'bg-blue-600 text-white border-blue-600'
                    : 'bg-white text-slate-600 border-slate-200 hover:bg-slate-50'}
                `}
              >
                {p.label}
              </button>
            ))}
          </div>

          <div className="flex gap-1.5">
            <input
              type="text"
              value={custom}
              onChange={e => { setCustom(e.target.value); setCustomError(false) }}
              onKeyDown={e => e.key === 'Enter' && applyCustom(custom)}
              placeholder={isCustom ? formatBytes(value) : 'e.g. 500 MB'}
              className={`
                flex-1 text-xs px-2 py-1 border rounded-md
                focus:outline-none focus:ring-1
                ${customError ? 'border-red-400 focus:ring-red-400' : 'border-slate-200 focus:ring-blue-400'}
              `}
            />
            <button
              onClick={() => applyCustom(custom)}
              className="px-2 py-1 text-xs bg-blue-600 text-white rounded-md hover:bg-blue-700 transition-colors"
            >
              Set
            </button>
          </div>
          {customError && (
            <div className="text-[11px] text-red-500 mt-1">Try: 500 MB, 1.5 GB, 200 KB</div>
          )}
        </div>
      )}
    </div>
  )
}
