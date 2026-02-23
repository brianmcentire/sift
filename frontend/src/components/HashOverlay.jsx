import { formatBytes, formatDate } from '../utils.js'
import HostBadge from './HostBadge.jsx'
import HashCell from './HashCell.jsx'

export default function HashOverlay({ results, hashQuery, hostColorMap, onClose }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white shadow-sm overflow-hidden">
      {/* Overlay header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-100 bg-slate-50">
        <div className="flex items-center gap-2">
          <span className="text-[10px] uppercase tracking-widest text-slate-400 font-medium">
            Hash search
          </span>
          <code className="text-[11px] font-mono bg-slate-100 px-2 py-0.5 rounded text-slate-700">
            {hashQuery}
          </code>
          <span className="text-sm text-slate-400">
            — {results.length} result{results.length !== 1 ? 's' : ''}
          </span>
        </div>
        <button
          onClick={onClose}
          className="text-slate-400 hover:text-slate-700 text-xl leading-none transition-colors"
          title="Close hash search"
        >
          ×
        </button>
      </div>

      {/* Results table */}
      {results.length === 0 ? (
        <div className="flex items-center justify-center py-12 text-slate-400 text-sm">
          No files found with that hash.
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="border-b border-slate-100">
                <th className="px-4 pb-2 pt-3 text-[10px] uppercase tracking-widest text-slate-400 font-medium">Path</th>
                <th className="px-4 pb-2 pt-3 text-[10px] uppercase tracking-widest text-slate-400 font-medium text-right">Size</th>
                <th className="px-4 pb-2 pt-3 text-[10px] uppercase tracking-widest text-slate-400 font-medium">Date</th>
                <th className="px-4 pb-2 pt-3 text-[10px] uppercase tracking-widest text-slate-400 font-medium">Hash</th>
                <th className="px-4 pb-2 pt-3 text-[10px] uppercase tracking-widest text-slate-400 font-medium">Host</th>
              </tr>
            </thead>
            <tbody>
              {results.map((f, i) => (
                <tr
                  key={i}
                  className="border-b border-slate-50 hover:bg-slate-50 transition-colors duration-100"
                >
                  <td className="px-4 py-2 font-mono text-[12px] text-slate-600 max-w-sm truncate" title={f.path_display}>
                    {f.path_display}
                  </td>
                  <td className="px-4 py-2 text-right text-sm text-slate-500 tabular-nums whitespace-nowrap">
                    {formatBytes(f.size_bytes)}
                  </td>
                  <td className="px-4 py-2 text-sm text-slate-400 tabular-nums whitespace-nowrap">
                    {formatDate(f.mtime)}
                  </td>
                  <td className="px-4 py-2">
                    <HashCell hash={f.hash} />
                  </td>
                  <td className="px-4 py-2">
                    <HostBadge host={f.host} hostColorMap={hostColorMap} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
