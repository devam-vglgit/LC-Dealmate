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

/** Centralises the 401 path so every caller can't forget it. */
function guard(res) {
  if (res.status === 401) {
    setToken(null)
    onUnauthorized()
    throw new Error('Your session expired — please sign in again.')
  }
  return res
}

export async function login(username, password) {
  const res = await fetch('/api/login', {
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

export function logout() {
  setToken(null)
}

export async function fetchHealth() {
  const res = await fetch('/api/health')
  if (!res.ok) throw new Error(`health: ${res.status}`)
  return res.json()
}

export async function fetchInventory() {
  const res = guard(await fetch('/api/inventory', { headers: headers() }))
  if (!res.ok) throw new Error(`inventory: ${res.status}`)
  return res.json()
}

export async function addSoftware(item) {
  const res = guard(
    await fetch('/api/inventory', {
      method: 'POST',
      headers: headers({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(item),
    }),
  )
  if (!res.ok) {
    const body = await res.json().catch(() => null)
    const detail = body?.detail
    const message = Array.isArray(detail)
      ? detail.map((d) => d.msg).join('; ')
      : detail || `Request failed (${res.status})`
    throw new Error(message)
  }
  return res.json()
}

export async function deleteSoftware(id) {
  const res = guard(
    await fetch(`/api/inventory/${encodeURIComponent(id)}`, {
      method: 'DELETE',
      headers: headers(),
    }),
  )
  if (!res.ok) throw new Error(`delete failed (${res.status})`)
  return res.json()
}

export async function listConversations() {
  const res = guard(await fetch('/api/conversations', { headers: headers() }))
  if (!res.ok) throw new Error(`conversations: ${res.status}`)
  return (await res.json()).conversations
}

export async function getConversation(id) {
  const res = guard(
    await fetch(`/api/conversations/${encodeURIComponent(id)}`, { headers: headers() }),
  )
  if (!res.ok) throw new Error(`conversation: ${res.status}`)
  return res.json()
}

export async function renameConversation(id, title) {
  const res = guard(
    await fetch(`/api/conversations/${encodeURIComponent(id)}/rename`, {
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
    await fetch(`/api/conversations/${encodeURIComponent(id)}`, {
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
 * EventSource can't POST, so we read the SSE body off fetch directly.
 */
export async function streamChat({ message, conversationId, focusId }, onEvent, signal) {
  const res = await fetch('/api/chat', {
    method: 'POST',
    headers: headers({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({
      message,
      ...(conversationId ? { conversation_id: conversationId } : {}),
      ...(focusId ? { focus_id: focusId } : {}),
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

    // SSE frames are separated by a blank line.
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
