const money = (n, currency) =>
  n == null
    ? '—'
    : new Intl.NumberFormat('en-US', {
        style: 'currency',
        currency: currency || 'USD',
        maximumFractionDigits: 0,
      }).format(n)

function renewalClass(days) {
  if (days == null) return ''
  if (days < 0) return 'chip chip-past'
  if (days <= 90) return 'chip chip-soon'
  return 'chip'
}

export default function InventoryPanel({ inventory, error, onAddClick, onDelete, onSelect, activeId }) {
  if (error) return <aside className="panel"><p className="muted">{error}</p></aside>
  if (!inventory) return <aside className="panel"><p className="muted">Loading stack…</p></aside>

  const { currency, software = [], total_annual_spend, line_item_count } = inventory
  const sorted = [...software].sort(
    (a, b) => (a.days_until_renewal ?? 1e9) - (b.days_until_renewal ?? 1e9),
  )

  return (
    <aside className="panel">
      <div className="panel-head">
        <h2>Current stack</h2>
        <button className="add-btn" onClick={onAddClick} title="Add software">
          +
        </button>
      </div>
      <div className="totals">
        <div>
          <span className="totals-value">{money(total_annual_spend, currency)}</span>
          <span className="muted">annual spend</span>
        </div>
        <div>
          <span className="totals-value">{line_item_count}</span>
          <span className="muted">contracts</span>
        </div>
      </div>

      <ul className="stack">
        {sorted.map((s) => (
          <li
            key={s.id || `${s.vendor}-${s.product}`}
            className={`stack-item${s.id === activeId ? ' stack-item-active' : ''}`}
          >
            <div className="stack-head">
              {s.id && onSelect ? (
                <button className="stack-name" onClick={() => onSelect(s)} title="View details">
                  {s.product}
                </button>
              ) : (
                <strong>{s.product}</strong>
              )}
              <span className="stack-head-right">
                <span className={renewalClass(s.days_until_renewal)}>
                  {s.days_until_renewal == null
                    ? 'no date'
                    : s.days_until_renewal < 0
                      ? 'expired'
                      : `${s.days_until_renewal}d`}
                </span>
                {s.id && onDelete && (
                  <button
                    className="remove-btn"
                    title="Remove"
                    onClick={() => onDelete(s.id, s.product)}
                  >
                    ×
                  </button>
                )}
              </span>
            </div>
            <div className="muted small">
              {s.vendor}
              {s.plan ? ` · ${s.plan}` : ''}
              {s.seats ? ` · ${s.seats} seats` : ''}
            </div>
            <div className="small">{money(s.annual_cost, currency)}/yr</div>
          </li>
        ))}
      </ul>
      {software.length === 0 && (
        <p className="muted small">
          No inventory loaded. Fill in <code>backend/data/software_inventory.json</code>.
        </p>
      )}
    </aside>
  )
}
