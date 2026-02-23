import { pathSegments } from '../utils.js'

export default function Breadcrumb({ currentPath, onNavigate }) {
  const segments = pathSegments(currentPath)

  function buildPath(index) {
    return '/' + segments.slice(0, index + 1).join('/')
  }

  return (
    <nav className="flex items-center gap-1 py-2 text-[12px] text-slate-500 select-none">
      <button
        onClick={() => onNavigate('/')}
        className={`
          hover:text-blue-600 transition-colors duration-150
          ${currentPath === '/' ? 'text-blue-600 font-semibold' : 'text-slate-500'}
        `}
      >
        /
      </button>

      {segments.map((seg, i) => (
        <span key={i} className="flex items-center gap-1">
          <span className="text-slate-300">›</span>
          <button
            onClick={() => onNavigate(buildPath(i))}
            className={`
              hover:text-blue-600 transition-colors duration-150
              ${i === segments.length - 1 ? 'text-blue-600 font-semibold' : 'text-slate-500'}
            `}
          >
            {seg}
          </button>
        </span>
      ))}
    </nav>
  )
}
