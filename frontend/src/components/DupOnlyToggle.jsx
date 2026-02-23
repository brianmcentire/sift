// value: bool, onChange: (bool) => void
export default function DupOnlyToggle({ value, onChange }) {
  return (
    <button
      onClick={() => onChange(!value)}
      className={`
        text-sm px-2.5 py-1.5
        bg-white border rounded-lg cursor-pointer
        focus:outline-none focus:ring-2 focus:ring-blue-400
        transition-all duration-150 whitespace-nowrap
        ${value ? 'border-blue-300 text-blue-600' : 'border-slate-200 text-slate-600'}
      `}
    >
      {value ? 'Only dups' : 'All files'}
    </button>
  )
}
