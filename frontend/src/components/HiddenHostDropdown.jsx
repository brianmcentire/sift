import { useState, useRef, useEffect } from 'react'

export default function HiddenHostDropdown({ hiddenHosts, selectedHosts, setSelectedHosts, promotedHiddenHosts, setPromotedHiddenHosts, hostColorMap }) {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)

  // Close on outside click
  useEffect(() => {
    if (!open) return
    function handler(e) {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  const promotedCount = hiddenHosts.filter(h => promotedHiddenHosts.has(h.host)).length

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen(o => !o)}
        className={`
          rounded-full px-3 py-1 text-[11px] font-semibold uppercase tracking-widest
          cursor-pointer transition-all duration-150 whitespace-nowrap
          ${promotedCount > 0
            ? 'border border-slate-400 bg-slate-100 text-slate-700'
            : 'border border-dashed border-slate-300 text-slate-400 bg-white hover:bg-slate-50'
          }
        `}
      >
        Hidden{promotedCount > 0 && ` (${promotedCount})`}
      </button>

      {open && (
        <div className="absolute left-0 top-full mt-1 z-50 min-w-[180px] rounded-lg border border-slate-200 bg-white shadow-lg py-1">
          {hiddenHosts.map(h => {
            const promoted = promotedHiddenHosts.has(h.host)
            const colors = hostColorMap.get(h.host)
            return (
              <label
                key={h.host}
                className="flex items-center gap-2 px-3 py-1.5 hover:bg-slate-50 cursor-pointer text-[12px]"
              >
                <input
                  type="checkbox"
                  checked={promoted}
                  onChange={() => {
                    if (promoted) {
                      // Uncheck: remove from promoted AND deselect
                      setPromotedHiddenHosts(prev => {
                        const next = new Set(prev)
                        next.delete(h.host)
                        return next
                      })
                      setSelectedHosts(prev => {
                        const next = new Set(prev)
                        next.delete(h.host)
                        return next
                      })
                    } else {
                      // Check: promote AND select
                      setPromotedHiddenHosts(prev => new Set(prev).add(h.host))
                      setSelectedHosts(prev => new Set(prev).add(h.host))
                    }
                  }}
                  className="rounded border-slate-300"
                />
                <span className={`font-semibold uppercase tracking-wider ${promoted && colors ? colors.badge.split(' ').filter(c => c.startsWith('text-'))[0] || 'text-slate-700' : 'text-slate-500'}`}>
                  {h.host}
                </span>
                {h.label && (
                  <span className="text-slate-400 text-[11px] truncate">{h.label}</span>
                )}
              </label>
            )
          })}
        </div>
      )}
    </div>
  )
}
