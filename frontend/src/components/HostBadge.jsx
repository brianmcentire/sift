export default function HostBadge({ host, hostColorMap }) {
  const colors = hostColorMap.get(host)
  if (!colors) return null

  return (
    <span className={`
      inline-block rounded-full px-2 py-0.5
      text-[10px] font-semibold uppercase tracking-wide
      leading-none whitespace-nowrap
      ${colors.badge}
    `}>
      {host}
    </span>
  )
}
