import { useState } from 'react'
import { addSoftware } from '../api'

const EMPTY = {
  vendor: '',
  product: '',
  category: '',
  plan: '',
  seats: '',
  unit_price_annual: '',
  annual_cost: '',
  contract_start: '',
  renewal_date: '',
  auto_renew: true,
  notice_period_days: '',
  owner: '',
  business_criticality: '',
  utilization_pct: '',
  notes: '',
}

// Fields the backend treats as numbers/booleans — everything else stays a string.
const NUMBER_FIELDS = ['seats', 'unit_price_annual', 'annual_cost', 'notice_period_days', 'utilization_pct']

function toPayload(form) {
  const out = {}
  for (const [key, value] of Object.entries(form)) {
    if (value === '' || value == null) continue
    out[key] = NUMBER_FIELDS.includes(key) ? Number(value) : value
  }
  return out
}

export default function AddSoftwareModal({ onClose, onAdded }) {
  const [form, setForm] = useState(EMPTY)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)

  const set = (key) => (e) => {
    const value = e.target.type === 'checkbox' ? e.target.checked : e.target.value
    setForm((f) => ({ ...f, [key]: value }))
  }

  async function submit(e) {
    e.preventDefault()
    if (!form.vendor.trim() || !form.product.trim()) {
      setError('Vendor and product are required.')
      return
    }
    setSaving(true)
    setError(null)
    try {
      const inventory = await addSoftware(toPayload(form))
      onAdded(inventory)
      onClose()
    } catch (err) {
      setError(err.message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <form className="modal" onClick={(e) => e.stopPropagation()} onSubmit={submit}>
        <div className="modal-head">
          <h3>Add software</h3>
          <button type="button" className="modal-close" onClick={onClose} aria-label="Close">
            ×
          </button>
        </div>

        {error && <div className="error">{error}</div>}

        <div className="field-grid">
          <label>
            Vendor *
            <input value={form.vendor} onChange={set('vendor')} required autoFocus />
          </label>
          <label>
            Product *
            <input value={form.product} onChange={set('product')} required />
          </label>
          <label>
            Category
            <input value={form.category} onChange={set('category')} placeholder="CRM, helpdesk…" />
          </label>
          <label>
            Plan / tier
            <input value={form.plan} onChange={set('plan')} placeholder="Pro, Enterprise…" />
          </label>
          <label>
            Seats
            <input type="number" min="0" value={form.seats} onChange={set('seats')} />
          </label>
          <label>
            Unit price / seat / yr
            <input type="number" min="0" step="0.01" value={form.unit_price_annual} onChange={set('unit_price_annual')} />
          </label>
          <label>
            Annual cost (total)
            <input type="number" min="0" step="0.01" value={form.annual_cost} onChange={set('annual_cost')} />
          </label>
          <label>
            Utilization %
            <input type="number" min="0" max="100" value={form.utilization_pct} onChange={set('utilization_pct')} />
          </label>
          <label>
            Contract start
            <input type="date" value={form.contract_start} onChange={set('contract_start')} />
          </label>
          <label>
            Renewal date
            <input type="date" value={form.renewal_date} onChange={set('renewal_date')} />
          </label>
          <label>
            Cancellation notice (days)
            <input type="number" min="0" value={form.notice_period_days} onChange={set('notice_period_days')} />
          </label>
          <label>
            Criticality
            <select value={form.business_criticality} onChange={set('business_criticality')}>
              <option value="">—</option>
              <option value="low">Low</option>
              <option value="medium">Medium</option>
              <option value="high">High</option>
            </select>
          </label>
          <label>
            Owner
            <input value={form.owner} onChange={set('owner')} placeholder="IT, Sales Ops…" />
          </label>
          <label className="checkbox-field">
            <input type="checkbox" checked={form.auto_renew} onChange={set('auto_renew')} />
            Auto-renews
          </label>
        </div>

        <label className="full-width">
          Notes
          <textarea rows={2} value={form.notes} onChange={set('notes')} />
        </label>

        <div className="modal-actions">
          <button type="button" className="secondary" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" disabled={saving}>
            {saving ? 'Saving…' : 'Add software'}
          </button>
        </div>
      </form>
    </div>
  )
}
