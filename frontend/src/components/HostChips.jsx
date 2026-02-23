export default function HostChips({ hosts, selectedHosts, setSelectedHosts, hostColorMap }) {
  const allSelected = selectedHosts.size === hosts.length

  function toggleAll() {
    if (allSelected) {
      // Deselect all → keep at least one (select first)
      setSelectedHosts(new Set(hosts.length ? [hosts[0].host] : []))
    } else {
      setSelectedHosts(new Set(hosts.map(h => h.host)))
    }
  }

  function toggleHost(hostName) {
    setSelectedHosts(prev => {
      const next = new Set(prev)
      if (next.has(hostName)) {
        if (next.size === 1) return prev // keep at least one
        next.delete(hostName)
      } else {
        next.add(hostName)
      }
      return next
    })
  }

  if (hosts.length === 0) return null

  return (
    <div className="flex items-center gap-1.5 flex-wrap">
      {hosts.map(h => {
        const colors = hostColorMap.get(h.host)
        const isActive = selectedHosts.has(h.host)
        return (
          <button
            key={h.host}
            onClick={() => toggleHost(h.host)}
            className={`
              rounded-full px-3 py-1 text-[11px] font-semibold uppercase tracking-widest
              cursor-pointer transition-all duration-150 whitespace-nowrap
              ${isActive ? colors.active : colors.inactive}
            `}
          >
            {h.host}
          </button>
        )
      })}
      <button
        onClick={toggleAll}
        className={`
          rounded-full px-3 py-1 text-[11px] font-semibold uppercase tracking-widest
          cursor-pointer transition-all duration-150
          ${allSelected
            ? 'bg-slate-700 text-white'
            : 'border border-slate-300 text-slate-500 bg-white hover:bg-slate-50'
          }
        `}
      >
        all
      </button>
    </div>
  )
}
