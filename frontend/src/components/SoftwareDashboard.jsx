import { useEffect, useState } from 'react'
import { fetchContractDocument } from '../api'

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

function PdfPane({ item }) {
  const [open, setOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [doc, setDoc] = useState(null)

  const canOpen = item?.source === 'cms' && (item.has_document || item.document_name)

  useEffect(() => {
    setOpen(false)
    setError(null)
    setLoading(false)
    setDoc((prev) => {
      if (prev?.url) URL.revokeObjectURL(prev.url)
      return null
    })
  }, [item?.id])

  useEffect(() => {
    return () => {
      if (doc?.url) URL.revokeObjectURL(doc.url)
    }
  }, [doc?.url])

  if (!canOpen) return null

  async function toggle() {
    if (open) {
      setOpen(false)
      return
    }
    setOpen(true)
    if (doc) return
    setLoading(true)
    setError(null)
    try {
      setDoc(await fetchContractDocument(item.id))
    } catch (e) {
      setError(e.message || 'Could not open that PDF.')
    } finally {
      setLoading(false)
    }
  }

  const isPdf = !doc || (doc.type || '').includes('pdf')

  return (
    <div className="pdf-pane">
      <div className="pdf-pane-actions">
        <button type="button" className="pdf-open-btn" onClick={toggle} disabled={loading}>
          {loading ? 'Loading PDF…' : open ? 'Hide PDF' : 'Open PDF'}
        </button>
        {item.document_name && <span className="muted small">{item.document_name}</span>}
        {doc?.url && (
          <a className="pdf-new-tab" href={doc.url} target="_blank" rel="noreferrer">
            Open in new tab
          </a>
        )}
      </div>
      {open && (
        <div className="pdf-frame-wrap">
          {error && <p className="attachment-error">{error}</p>}
          {doc?.url && isPdf && <iframe className="pdf-frame" title={doc.filename} src={doc.url} />}
          {doc?.url && !isPdf && (
            <p className="muted small">
              This file is not a PDF.{' '}
              <a href={doc.url} download={doc.filename}>
                Download {doc.filename}
              </a>
            </p>
          )}
        </div>
      )}
    </div>
  )
}

function present(value) {
  if (value == null) return false
  if (typeof value === 'string' && !value.trim()) return false
  if (value === '—' || value === '.' || value === '-') return false
  return true
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
    recorded_value,
    value_basis,
    contract_start,
    renewal_date,
    auto_renew,
    notice_period_days,
    owner,
    department,
    legal_entity,
    status,
    parties,
    contract_structure,
    sharing_basis,
    business_criticality,
    utilization_pct,
    notes,
    days_until_renewal,
    days_until_cancellation_deadline,
  } = item

  const cancelPast = days_until_cancellation_deadline != null && days_until_cancellation_deadline < 0
  const meta = [vendor, department, legal_entity, status].filter(present)
  const stats = [
    present(annual_cost) && {
      label: 'Annual cost',
      value: money(annual_cost, currency),
    },
    present(recorded_value) && {
      label: value_basis ? `Recorded (${value_basis})` : 'Recorded',
      value: money(recorded_value, currency),
    },
    present(seats) && { label: 'Seats', value: seats },
    present(unit_price_annual) && {
      label: 'Per seat / yr',
      value: money(unit_price_annual, currency),
    },
    present(utilization_pct) && {
      label: 'Utilization',
      value: `${utilization_pct}%`,
      tone: utilization_pct < 60 ? 'warn' : null,
    },
    present(renewal_date) && {
      label: 'Ends',
      value: dateFmt(renewal_date),
      tone: renewalTone(days_until_renewal),
    },
    days_until_renewal != null && {
      label: days_until_renewal < 0 ? 'Expired' : 'Days left',
      value: days_until_renewal < 0 ? `${Math.abs(days_until_renewal)}d ago` : days_until_renewal,
      tone: renewalTone(days_until_renewal),
    },
    days_until_cancellation_deadline != null && {
      label: 'Notice deadline',
      value: cancelPast
        ? `passed ${Math.abs(days_until_cancellation_deadline)}d ago`
        : `in ${days_until_cancellation_deadline}d`,
      tone: cancelPast ? 'danger' : renewalTone(days_until_cancellation_deadline),
    },
    auto_renew != null && { label: 'Auto-renews', value: auto_renew ? 'Yes' : 'No' },
    present(contract_structure) && { label: 'Structure', value: contract_structure },
    present(contract_start) && { label: 'Start', value: dateFmt(contract_start) },
    notice_period_days != null && { label: 'Notice', value: `${notice_period_days}d` },
    present(owner) && { label: 'Owner', value: owner },
    present(category) && category !== plan && { label: 'Type', value: category },
    present(plan) && { label: 'Plan', value: plan },
  ].filter(Boolean)

  const extraNotes = [
    present(parties) && parties !== product && parties !== vendor && { label: 'Parties', text: parties },
    present(sharing_basis) && { label: 'Sharing', text: sharing_basis },
    present(notes) && { label: 'Notes', text: notes },
  ].filter(Boolean)

  return (
    <div className="dashboard">
      <button className="back-link" onClick={onBack}>
        ← All contracts
      </button>

      <div className="dashboard-head">
        <div>
          <h2>{vendor || product}</h2>
          <p className="muted">
            {product && vendor && product !== vendor ? `${product} · ` : ''}
            {meta.filter((m) => m !== vendor).join(' · ')}
          </p>
        </div>
        {business_criticality && (
          <span className={`chip chip-crit-${business_criticality}`}>{business_criticality}</span>
        )}
      </div>

      <PdfPane item={item} />

      <div className="stat-grid">
        {stats.map((s) => (
          <Stat key={s.label} label={s.label} value={s.value} tone={s.tone} />
        ))}
      </div>

      {extraNotes.length > 0 && (
        <div className="dashboard-notes">
          {extraNotes.map((n) => (
            <div key={n.label}>
              <span className="muted small">{n.label}</span>
              <p>{n.text}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
