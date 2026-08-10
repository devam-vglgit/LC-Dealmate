const money = (n, currency) =>
  n == null
    ? '—'
    : new Intl.NumberFormat('en-US', {
        style: 'currency',
        currency: currency || 'USD',
        maximumFractionDigits: 2,
      }).format(n)

const dateFmt = (iso) => {
  if (!iso) return '—'
  try {
    return new Date(iso + 'T00:00:00').toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    })
  } catch {
    return iso
  }
}

function Stat({ label, value, tone }) {
  return (
    <div className={`stat${tone ? ` stat-${tone}` : ''}`}>
      <span className="stat-value">{value}</span>
      <span className="stat-label">{label}</span>
    </div>
  )
}

function renewalTone(days) {
  if (days == null) return null
  if (days < 0) return 'danger'
  if (days <= 90) return 'warn'
  return null
}

export default function SoftwareDashboard({ item, currency, onBack }) {
  const {
    vendor,
    product,
    category,
    plan,
    seats,
    unit_price_annual,
    annual_cost,
    contract_start,
    renewal_date,
    auto_renew,
    notice_period_days,
    owner,
    business_criticality,
    utilization_pct,
    notes,
    days_until_renewal,
    days_until_cancellation_deadline,
  } = item

  const cancelPast = days_until_cancellation_deadline != null && days_until_cancellation_deadline < 0

  return (
    <div className="dashboard">
      <button className="back-link" onClick={onBack}>
        ← All software
      </button>

      <div className="dashboard-head">
        <div>
          <h2>{product}</h2>
          <p className="muted">
            {vendor}
            {plan ? ` · ${plan}` : ''}
            {category ? ` · ${category}` : ''}
          </p>
        </div>
        {business_criticality && (
          <span className={`chip chip-crit-${business_criticality}`}>{business_criticality} criticality</span>
        )}
      </div>

      <div className="stat-grid">
        <Stat label="Annual cost" value={money(annual_cost, currency)} />
        <Stat label="Seats" value={seats ?? '—'} />
        <Stat label="Unit price / seat / yr" value={money(unit_price_annual, currency)} />
        <Stat
          label="Utilization"
          value={utilization_pct != null ? `${utilization_pct}%` : '—'}
          tone={utilization_pct != null && utilization_pct < 60 ? 'warn' : null}
        />
        <Stat label="Renewal date" value={dateFmt(renewal_date)} tone={renewalTone(days_until_renewal)} />
        <Stat
          label="Days to renewal"
          value={days_until_renewal == null ? '—' : days_until_renewal < 0 ? 'expired' : days_until_renewal}
          tone={renewalTone(days_until_renewal)}
        />
        <Stat
          label="Cancellation deadline"
          value={
            days_until_cancellation_deadline == null
              ? '—'
              : cancelPast
                ? `passed ${Math.abs(days_until_cancellation_deadline)}d ago`
                : `in ${days_until_cancellation_deadline}d`
          }
          tone={cancelPast ? 'danger' : renewalTone(days_until_cancellation_deadline)}
        />
        <Stat label="Auto-renews" value={auto_renew == null ? '—' : auto_renew ? 'Yes' : 'No'} />
        <Stat label="Contract start" value={dateFmt(contract_start)} />
        <Stat label="Notice period" value={notice_period_days != null ? `${notice_period_days}d` : '—'} />
        <Stat label="Owner" value={owner || '—'} />
      </div>

      {notes && (
        <div className="dashboard-notes">
          <span className="muted small">Notes</span>
          <p>{notes}</p>
        </div>
      )}
    </div>
  )
}
