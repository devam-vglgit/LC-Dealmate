import { useEffect, useMemo, useState } from 'react'

const FILTERS = [
  { id: 'active', label: 'Active' },
  { id: 'expiring', label: 'Expiring' },
  { id: 'expired', label: 'Expired' },
  { id: 'all', label: 'All' },
]

const money = (n, currency) =>
  n == null
    ? '—'
    : new Intl.NumberFormat('en-US', {
        style: 'currency',
        currency: currency || 'USD',
        maximumFractionDigits: 0,
      }).format(n)

export function contractStatus(item) {
  const raw = (item?.status || '').toLowerCase()
  if (raw === 'expired' || raw === 'expiring' || raw === 'active') return raw
  const days = item?.days_until_renewal
  if (days == null) return 'active'
  if (days < 0) return 'expired'
  if (days <= 90) return 'expiring'
  return 'active'
}

function statusRank(status) {
  if (status === 'active') return 0
  if (status === 'expiring') return 1
  if (status === 'expired') return 2
  return 3
}

function sortContracts(list) {
  return [...list].sort((a, b) => {
    const ra = statusRank(contractStatus(a))
    const rb = statusRank(contractStatus(b))
    if (ra !== rb) return ra - rb
    const da = a.days_until_renewal
    const db = b.days_until_renewal
    if (da == null && db == null) return 0
    if (da == null) return 1
    if (db == null) return -1
    // Live deals: soonest first. Expired: most recently ended first.
    if (ra === 2) return db - da
    return da - db
  })
}

function renewalChip(item) {
  const status = contractStatus(item)
  const days = item.days_until_renewal
  if (status === 'expired' || days < 0) return { cls: 'chip chip-past', text: 'Expired' }
  if (status === 'expiring' || (days != null && days <= 90)) {
    return { cls: 'chip chip-soon', text: days == null ? 'Expiring' : `${days}d` }
  }
  if (days == null) return { cls: 'chip', text: 'Active' }
  return { cls: 'chip chip-ok', text: `${days}d` }
}

function nameHaystack(item) {
  return [
    item.vendor,
    item.product,
    item.parties,
    item.department,
    item.category,
    item.legal_entity,
  ]
    .filter(Boolean)
    .join(' ')
    .toLowerCase()
}

const EMPTY = []

export default function InventoryPanel({
  inventory,
  error,
  sharesContracts,
  onSelect,
  activeId,
}) {
  const [filter, setFilter] = useState('active')
  const [query, setQuery] = useState('')
  const software = inventory?.software || EMPTY
  const currency = inventory?.currency

  const counts = useMemo(() => {
    const next = { active: 0, expiring: 0, expired: 0, all: software.length }
    for (const s of software) next[contractStatus(s)] += 1
    return next
  }, [software])

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase()
    const filtered =
      filter === 'all' ? software : software.filter((s) => contractStatus(s) === filter)
    const named = q ? filtered.filter((s) => nameHaystack(s).includes(q)) : filtered
    return sortContracts(named)
  }, [software, filter, query])

  useEffect(() => {
    if (!activeId) return
    const item = software.find((s) => s.id === activeId)
    if (!item) return
    const status = contractStatus(item)
    setFilter((current) => (current === 'all' || current === status ? current : status))
  }, [activeId, software])

  if (error) return <aside className="panel"><p className="muted">{error}</p></aside>
  if (!inventory) return <aside className="panel"><p className="muted">Loading…</p></aside>

  const shownSpend = visible.reduce(
    (sum, s) => sum + (Number(s.annual_cost ?? s.recorded_value) || 0),
    0,
  )

  const entities = [...new Set(software.map((s) => s.legal_entity || null))]
  const scope = entities.length === 1 ? entities[0] : null
  const heading = scope || 'Contracts'

  return (
    <aside className="panel">
      <div className="panel-head">
        <h2 title={heading}>{heading}</h2>
      </div>

      <div className="contract-search">
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search by name…"
          aria-label="Search contracts by name"
        />
      </div>

      <div className="totals">
        <div>
          <span className="totals-value">{money(shownSpend || null, currency)}</span>
          <span className="muted">shown / yr</span>
        </div>
        <div>
          <span className="totals-value">{visible.length}</span>
          <span className="muted">{filter === 'all' ? 'contracts' : filter}</span>
        </div>
      </div>

      <div className="filter-bar" role="tablist" aria-label="Filter contracts">
        {FILTERS.map((f) => (
          <button
            key={f.id}
            type="button"
            role="tab"
            aria-selected={filter === f.id}
            className={`filter-btn${filter === f.id ? ' is-on' : ''}`}
            onClick={() => setFilter(f.id)}
          >
            {f.label}
            <span className="filter-count">{counts[f.id] || 0}</span>
          </button>
        ))}
      </div>

      {sharesContracts != null && (
        <p className="muted small cms-status">
          <span
            className={sharesContracts ? 'ai-scope ai-scope-on' : 'ai-scope'}
            title={
              sharesContracts
                ? 'The AI sees de-identified terms only. It cannot edit contracts or PDFs.'
                : 'No contract data is sent to the AI.'
            }
          >
            {sharesContracts ? 'AI: read-only terms' : 'AI: not sent'}
          </span>
        </p>
      )}

      <ul className="stack">
        {visible.map((s) => {
          const chip = renewalChip(s)
          return (
            <li
              key={s.id || `${s.vendor}-${s.product}`}
              className={`stack-item${s.id === activeId ? ' stack-item-active' : ''}`}
            >
              <div className="stack-head">
                {s.id && onSelect ? (
                  <button className="stack-name" onClick={() => onSelect(s)} title="Open">
                    {s.vendor || s.product}
                  </button>
                ) : (
                  <strong>{s.vendor || s.product}</strong>
                )}
                <span className="stack-head-right">
                  <span className={chip.cls}>{chip.text}</span>
                </span>
              </div>
              <div className="muted small stack-meta">
                {s.department || s.category || ''}
                {s.department && s.category ? ` · ${s.category}` : ''}
              </div>
              <div className="small stack-cost">
                {money(s.annual_cost ?? s.recorded_value, s.currency || currency)}
              </div>
            </li>
          )
        })}
      </ul>
      {software.length === 0 && (
        <p className="muted small">No contracts loaded. Check CMS connectivity.</p>
      )}
      {software.length > 0 && visible.length === 0 && (
        <p className="muted small">
          {query.trim()
            ? `No contracts match “${query.trim()}”.`
            : `No ${filter} contracts.`}
        </p>
      )}
    </aside>
  )
}
