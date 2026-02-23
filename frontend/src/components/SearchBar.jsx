export default function SearchBar({ value, onChange, placeholder = 'filename…', className = '' }) {
  return (
    <div className={`relative ${className}`}>
      <span className="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400 text-sm pointer-events-none">
        🔍
      </span>
      <input
        type="text"
        value={value}
        onChange={e => onChange(e.target.value)}
        placeholder={placeholder}
        className="
          w-full pl-8 pr-3 py-1.5 text-sm
          bg-white border border-slate-200 rounded-lg
          placeholder-slate-400 text-slate-700
          focus:outline-none focus:ring-2 focus:ring-blue-400 focus:border-transparent
          transition-all duration-150
        "
      />
      {value && (
        <button
          onClick={() => onChange('')}
          className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600 text-lg leading-none"
        >
          ×
        </button>
      )}
    </div>
  )
}
