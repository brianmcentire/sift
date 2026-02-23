import { useState, useRef, useEffect } from 'react'
import { api } from '../api.js'

export default function DirectorySearch({ value, onSelect, onClear, className = '' }) {
  const [suggestions, setSuggestions] = useState([])
  const [open, setOpen] = useState(false)
  const [activeIdx, setActiveIdx] = useState(-1)
  const ref = useRef(null)
  const timerRef = useRef(null)

  // Click outside → close
  useEffect(() => {
    function handle(e) {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false)
    }
    document.addEventListener('mousedown', handle)
    return () => document.removeEventListener('mousedown', handle)
  }, [])

  function handleChange(e) {
    const val = e.target.value
    setActiveIdx(-1)
    // Propagate text change upward so parent can sync display value
    onSelect({ dir_path: null, dir_display: val, _typing: true })
    clearTimeout(timerRef.current)
    if (val.length < 2) {
      setSuggestions([])
      setOpen(false)
      if (!val) onClear()
      return
    }
    timerRef.current = setTimeout(async () => {
      try {
        const data = await api.directories(val)
        setSuggestions(data)
        setOpen(data.length > 0)
      } catch {
        setSuggestions([])
        setOpen(false)
      }
    }, 150)
  }

  function handleSelect(sug) {
    setSuggestions([])
    setOpen(false)
    setActiveIdx(-1)
    onSelect(sug)
  }

  function handleKeyDown(e) {
    if (!open) return
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setActiveIdx(i => Math.min(i + 1, suggestions.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActiveIdx(i => Math.max(i - 1, 0))
    } else if (e.key === 'Enter' && activeIdx >= 0) {
      e.preventDefault()
      handleSelect(suggestions[activeIdx])
    } else if (e.key === 'Escape') {
      setOpen(false)
    }
  }

  return (
    <div ref={ref} className={`relative ${className}`}>
      <div className="relative">
        <span className="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400 text-sm pointer-events-none">
          📁
        </span>
        <input
          type="text"
          value={value}
          onChange={handleChange}
          onKeyDown={handleKeyDown}
          placeholder="directory…"
          className="
            w-full pl-8 pr-7 py-1.5 text-sm
            bg-white border border-slate-200 rounded-lg
            placeholder-slate-400 text-slate-700
            focus:outline-none focus:ring-2 focus:ring-blue-400 focus:border-transparent
            transition-all duration-150
          "
        />
        {value && (
          <button
            onClick={onClear}
            className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600 text-lg leading-none"
            tabIndex={-1}
          >
            ×
          </button>
        )}
      </div>

      {open && suggestions.length > 0 && (
        <div className="absolute left-0 top-full mt-1 z-50 bg-white border border-slate-200 rounded-xl shadow-lg py-1 w-72 max-h-60 overflow-y-auto">
          {suggestions.map((sug, i) => (
            <button
              key={sug.dir_path}
              className={`w-full text-left px-3 py-1.5 text-[12px] font-mono truncate transition-colors ${
                i === activeIdx ? 'bg-blue-50 text-blue-700' : 'text-slate-700 hover:bg-slate-50'
              }`}
              onMouseDown={e => { e.preventDefault(); handleSelect(sug) }}
            >
              {sug.dir_display || sug.dir_path}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
