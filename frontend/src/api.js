// In Vite dev, /api is proxied to the backend. In CMS production the SPA is
// served from the same origin as FastAPI, so the empty default is correct.
const API_BASE = (import.meta.env?.VITE_API_BASE || '').replace(/\/+$/, '')

const TOKEN_KEY = 'lc_dealmate_token'
let token = localStorage.getItem(TOKEN_KEY) || null
let onUnauthorized = () => {}

export function getToken() {
  return token
}

export function setToken(value) {
  token = value || null
  if (token) localStorage.setItem(TOKEN_KEY, token)
  else localStorage.removeItem(TOKEN_KEY)
}

/** App registers this so an expired session bounces straight back to login. */
export function setUnauthorizedHandler(fn) {
  onUnauthorized = fn || (() => {})
}

function headers(extra = {}) {
  return token ? { ...extra, Authorization: `Bearer ${token}` } : extra
}

function guard(res) {
  if (res.status === 401) {
    setToken(null)
    onUnauthorized()
    throw new Error('Your session expired — please sign in again.')
  }
  return res
}

export async function login(username, password) {
  const res = await fetch(`${API_BASE}/api/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })
  if (!res.ok) {
    const body = await res.json().catch(() => null)
    throw new Error(body?.detail || `Login failed (${res.status})`)
  }
  const data = await res.json()
  setToken(data.token)
  return data
}

/** Exchange a CMS iframe JWT (?token=) for a DealMate session. */
export async function authCms(cmsToken) {
  const res = await fetch(`${API_BASE}/api/auth/cms`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ token: cmsToken }),
  })
  if (!res.ok) {
    const body = await res.json().catch(() => null)
    throw new Error(body?.detail || `CMS sign-in failed (${res.status})`)
  }
  const data = await res.json()
  setToken(data.token)
  return data
}

export function logout() {
  setToken(null)
}

export async function fetchHealth() {
  const res = await fetch(`${API_BASE}/api/health`)
  if (!res.ok) throw new Error(`health: ${res.status}`)
  return res.json()
}

export async function fetchInventory() {
  const res = guard(await fetch(`${API_BASE}/api/inventory`, { headers: headers() }))
  if (!res.ok) throw new Error(`inventory: ${res.status}`)
  return res.json()
}

/**
 * Downloads a CMS contract file to this browser only (blob URL).
 * The file is not sent to the model.
 */
export async function fetchContractDocument(id) {
  const res = guard(
    await fetch(`${API_BASE}/api/cms/contracts/${encodeURIComponent(id)}/document`, {
      headers: headers(),
    }),
  )
  if (!res.ok) {
    const body = await res.json().catch(() => null)
    throw new Error(body?.detail || `Could not open that PDF (${res.status})`)
  }
  const blob = await res.blob()
  const header = res.headers.get('content-disposition') || ''
  const match = header.match(/filename="([^"]+)"/)
  return {
    url: URL.createObjectURL(blob),
    type: blob.type || 'application/pdf',
    filename: match ? match[1] : 'contract.pdf',
  }
}

export async function listConversations() {
  const res = guard(await fetch(`${API_BASE}/api/conversations`, { headers: headers() }))
  if (!res.ok) throw new Error(`conversations: ${res.status}`)
  return (await res.json()).conversations
}

export async function getConversation(id) {
  const res = guard(
    await fetch(`${API_BASE}/api/conversations/${encodeURIComponent(id)}`, { headers: headers() }),
  )
  if (!res.ok) throw new Error(`conversation: ${res.status}`)
  return res.json()
}

export async function renameConversation(id, title) {
  const res = guard(
    await fetch(`${API_BASE}/api/conversations/${encodeURIComponent(id)}/rename`, {
      method: 'POST',
      headers: headers({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ title }),
    }),
  )
  if (!res.ok) throw new Error(`rename failed (${res.status})`)
  return (await res.json()).conversations
}

export async function deleteConversation(id) {
  const res = guard(
    await fetch(`${API_BASE}/api/conversations/${encodeURIComponent(id)}`, {
      method: 'DELETE',
      headers: headers(),
    }),
  )
  if (!res.ok) throw new Error(`delete failed (${res.status})`)
  return (await res.json()).conversations
}

/**
 * Sends one new message and invokes `onEvent` for each streamed event. Only the
 * message goes over the wire — the server replays stored history to the model.
 */
export async function uploadAttachment(file) {
  const body = new FormData()
  body.append('file', file)
  const res = guard(
    await fetch(`${API_BASE}/api/attachments`, {
      method: 'POST',
      headers: headers(),
      body,
    }),
  )
  if (!res.ok) {
    const err = await res.json().catch(() => null)
    throw new Error(err?.detail || `Upload failed (${res.status})`)
  }
  return res.json()
}

export function attachmentUrl(id) {
  return `${API_BASE}/api/attachments/${encodeURIComponent(id)}`
}

export async function streamChat({ message, conversationId, focusId, attachmentId }, onEvent, signal) {
  const res = await fetch(`${API_BASE}/api/chat`, {
    method: 'POST',
    headers: headers({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({
      message,
      ...(conversationId ? { conversation_id: conversationId } : {}),
      ...(focusId ? { focus_id: focusId } : {}),
      ...(attachmentId ? { attachment_id: attachmentId } : {}),
    }),
    signal,
  })
  if (res.status === 401) {
    setToken(null)
    onUnauthorized()
    onEvent({ type: 'error', message: 'Your session expired — please sign in again.' })
    return
  }
  if (!res.ok || !res.body) {
    onEvent({ type: 'error', message: `Request failed (${res.status})` })
    return
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    let split
    while ((split = buffer.indexOf('\n\n')) !== -1) {
      const frame = buffer.slice(0, split)
      buffer = buffer.slice(split + 2)
      for (const line of frame.split('\n')) {
        if (!line.startsWith('data: ')) continue
        try {
          onEvent(JSON.parse(line.slice(6)))
        } catch {
          /* ignore malformed frame */
        }
      }
    }
  }
}
