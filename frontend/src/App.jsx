import { useEffect, useMemo, useRef, useState } from 'react'
import {
  authCms,
  deleteConversation,
  fetchHealth,
  fetchInventory,
  getConversation,
  getToken,
  listConversations,
  logout,
  renameConversation,
  setUnauthorizedHandler,
  streamChat,
  uploadAttachment,
} from './api'
import Login from './components/Login'
import InventoryPanel from './components/InventoryPanel'
import ChatHistoryPanel from './components/ChatHistoryPanel'
import SoftwareDashboard from './components/SoftwareDashboard'
import Message from './components/Message'

const GENERAL_SUGGESTIONS = [
  'Compare vendors for a service we do not have a contract for yet.',
  'Prepare competitor research and talking points for a first vendor meeting.',
  'What discount is realistic for an enterprise renewal this year?',
  'How should we structure a multi-year deal versus a one-year renewal?',
]

const PORTFOLIO_SUGGESTIONS = [
  'Compare credible alternatives for a category we already buy — one table, vendors as columns.',
  'Which vendor is the best fit for our typical use case, and why?',
  'Which active, expiring, or expired contracts need attention in the next 90 days?',
  'Prepare negotiation points for a new service we have not contracted yet.',
]

const FOCUS_SUGGESTIONS = [
  'Compare this vendor with alternatives: services, use cases, limits, pricing, and features.',
  'Which alternative is the best fit for our use case, and why (service and cost)?',
  'What should we ask for at renewal or on a re-sign?',
]

const NEW_SERVICE_SUGGESTIONS = [
  'Research a new service: competitors, official pricing, limits, and what to ask in the first meeting.',
]

function SuggestionGroup({ label, items, onPick }) {
  if (!items?.length) return null
  return (
    <div className="suggestion-group">
      {label ? <p className="muted small suggestion-label">{label}</p> : null}
      <div className="suggestions">
        {items.map((s) => (
          <button key={s} type="button" onClick={() => onPick(s)}>
            {s}
          </button>
        ))}
      </div>
    </div>
  )
}

function inIframe() {
  try {
    return window.self !== window.top
  } catch {
    return true
  }
}

/** CMS opens `?token=<jwt>&contract=<uuid>&embed=1`. Read-only — stripping the JWT is an effect. */
function readLaunchParams() {
  const params = new URLSearchParams(window.location.search)
  return {
    cmsToken: params.get('token'),
    contractId: params.get('contract'),
    embed: params.get('embed') === '1' || inIframe(),
  }
}

export default function App() {
  const [launch] = useState(readLaunchParams)

  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    if (!params.has('token')) return
    params.delete('token')
    const qs = params.toString()
    window.history.replaceState(
      {},
      '',
      `${window.location.pathname}${qs ? `?${qs}` : ''}${window.location.hash}`,
    )
  }, [])

  const [authState, setAuthState] = useState(null)
  const [health, setHealth] = useState(null)
  const [authError, setAuthError] = useState(null)
  const [inventory, setInventory] = useState(null)
  const [invError, setInvError] = useState(null)
  const [focusItem, setFocusItem] = useState(null)
  const pendingContractId = useRef(launch.contractId)

  const [panelOpen, setPanelOpen] = useState(true)
  const [historyOpen, setHistoryOpen] = useState(!launch.embed)

  const [conversations, setConversations] = useState([])
  const [activeId, setActiveId] = useState(null)
  const [messages, setMessages] = useState([])

  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [attachment, setAttachment] = useState(null)
  const [attachError, setAttachError] = useState(null)
  const [attaching, setAttaching] = useState(false)
  const abortRef = useRef(null)
  const threadRef = useRef(null)
  const pinnedRef = useRef(true)
  const fileRef = useRef(null)

  const softwareById = useMemo(() => {
    const map = {}
    for (const s of inventory?.software || []) map[s.id] = s
    return map
  }, [inventory])

  useEffect(() => {
    setUnauthorizedHandler(() => setAuthState('anonymous'))
    let cancelled = false

    async function boot() {
      try {
        const h = await fetchHealth()
        if (cancelled) return
        setHealth(h)

        if (launch.cmsToken) {
          if (!h.cms_handoff) {
            setAuthError('CMS handoff is not configured on this server (set CMS_EMBED_SECRET).')
            setAuthState('anonymous')
            return
          }
          await authCms(launch.cmsToken)
          if (cancelled) return
          setAuthState('authed')
          return
        }

        if (!h.auth_required) {
          setAuthState('open')
          return
        }
        setAuthState(getToken() ? 'authed' : 'anonymous')
      } catch (e) {
        if (cancelled) return
        setAuthError(e.message || 'Could not reach the API. Is the backend running?')
        setAuthState('anonymous')
        setInvError('Could not reach the API. Is the backend running?')
      }
    }

    boot()
    return () => {
      cancelled = true
    }
  }, [launch.cmsToken])

  useEffect(() => {
    if (authState !== 'authed' && authState !== 'open') return

    fetchInventory()
      .then(setInventory)
      .catch(() => setInvError('Could not reach the API. Is the backend running?'))

    listConversations()
      .then(async (list) => {
        setConversations(list)
        if (pendingContractId.current) return
        if (list.length) await openConversation(list[0].id, list)
      })
      .catch(() => {})
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authState])

  useEffect(() => {
    const wanted = pendingContractId.current
    if (!wanted || !inventory) return
    const item = (inventory.software || []).find((s) => s.id === wanted)
    pendingContractId.current = null
    if (item) {
      handleSelectSoftware(item)
    } else {
      setInvError('CMS opened a contract that is not in this portfolio.')
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [inventory])

  useEffect(() => {
    const el = threadRef.current
    if (!el || !pinnedRef.current) return
    el.scrollTop = el.scrollHeight
  }, [messages, focusItem])

  function handleThreadScroll() {
    const el = threadRef.current
    if (!el) return
    pinnedRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80
  }

  async function refreshConversations() {
    try {
      setConversations(await listConversations())
    } catch {
      /* non-fatal — the sidebar just stays stale until the next turn */
    }
  }

  async function openConversation(id, listOverride) {
    abortRef.current?.abort()
    pinnedRef.current = true
    try {
      const conv = await getConversation(id)
      setActiveId(conv.id)
      const msgs = conv.messages || []
      setMessages(msgs)
      setAttachment(conv.attachment || null)
      setAttachError(null)
      const list = listOverride || conversations
      const focusId = conv.focus_id
      if (focusId) {
        const items = inventory?.software || []
        setFocusItem(items.find((s) => s.id === focusId) || null)
      } else {
        setFocusItem(null)
      }
      void list
    } catch {
      setInvError('Could not load that conversation.')
    }
  }

  useEffect(() => {
    if (!activeId || focusItem || !inventory) return
    const conv = conversations.find((c) => c.id === activeId)
    if (conv?.focus_id) setFocusItem(softwareById[conv.focus_id] || null)
  }, [inventory, activeId, conversations, focusItem, softwareById])

  function startNewChat(focus = null) {
    abortRef.current?.abort()
    pinnedRef.current = true
    setActiveId(null)
    setMessages([])
    setAttachment(null)
    setAttachError(null)
    setFocusItem(focus)
  }

  async function send(text) {
    const question = text.trim()
    if (busy || !question) return

    const conversationId = activeId
    const focusId = focusItem?.id || null
    const attachmentId = attachment?.id || null

    setMessages((prev) => [
      ...prev,
      { role: 'user', content: question, attachment: attachment?.filename || null },
      { role: 'assistant', content: '', searches: [] },
    ])
    setInput('')
    setBusy(true)
    pinnedRef.current = true

    const controller = new AbortController()
    abortRef.current = controller

    const patch = (fn) =>
      setMessages((prev) => {
        const next = [...prev]
        next[next.length - 1] = fn(next[next.length - 1])
        return next
      })

    try {
      await streamChat(
        { message: question, conversationId, focusId, attachmentId },
        (ev) => {
          switch (ev.type) {
            case 'conversation':
              setActiveId(ev.id)
              return
            case 'text':
              return patch((m) => ({ ...m, content: m.content + ev.text }))
            case 'thinking':
              return patch((m) => ({ ...m, thinking: (m.thinking || '') + ev.text }))
            case 'search_start':
              return patch((m) => ({ ...m, searches: [...(m.searches || []), null] }))
            case 'searches':
              return patch((m) => ({ ...m, searches: ev.queries }))
            case 'sources':
              return patch((m) => ({ ...m, sources: ev.items }))
            case 'status':
              return patch((m) => ({ ...m, status: ev.message }))
            case 'error':
              return patch((m) => ({ ...m, error: ev.message }))
            default:
              return undefined
          }
        },
        controller.signal,
      )
    } catch (e) {
      if (e.name !== 'AbortError') patch((m) => ({ ...m, error: String(e.message || e) }))
    } finally {
      setBusy(false)
      abortRef.current = null
      refreshConversations()
    }
  }

  async function handleDeleteConversation(id, title) {
    if (!window.confirm(`Delete chat "${title}"?`)) return
    try {
      setConversations(await deleteConversation(id))
      if (activeId === id) startNewChat()
    } catch (e) {
      setInvError(String(e.message || e))
    }
  }

  async function handleRenameConversation(id, current) {
    const title = window.prompt('Rename chat', current)
    if (title == null || !title.trim()) return
    try {
      setConversations(await renameConversation(id, title.trim()))
    } catch (e) {
      setInvError(String(e.message || e))
    }
  }

  function handleSelectSoftware(item) {
    const existing = conversations.find((c) => c.focus_id === item.id)
    if (existing) {
      openConversation(existing.id)
      setFocusItem(item)
    } else {
      startNewChat(item)
    }
  }

  const sharesContracts = !!health?.sends_contracts_to_model
  const suggestionGroups = !sharesContracts
    ? [{ label: 'Ask', items: GENERAL_SUGGESTIONS }]
    : focusItem
      ? [
          { label: 'This contract', items: FOCUS_SUGGESTIONS },
          { label: 'New service or general', items: NEW_SERVICE_SUGGESTIONS.concat(GENERAL_SUGGESTIONS.slice(2, 3)) },
        ]
      : [
          { label: 'Portfolio', items: PORTFOLIO_SUGGESTIONS },
          { label: 'New service or general', items: NEW_SERVICE_SUGGESTIONS.concat(GENERAL_SUGGESTIONS.slice(2)) },
        ]
  const placeholder = attachment
    ? `Ask about ${attachment.filename}…`
    : focusItem
      ? `Ask about ${focusItem.vendor || focusItem.product}, or a new service…`
      : 'Ask about a contract, a vendor, a new service, or attach a file…'

  async function handleAttach(file) {
    if (!file || attaching) return
    setAttachError(null)
    setAttaching(true)
    try {
      const saved = await uploadAttachment(file)
      setAttachment({ id: saved.id, filename: saved.filename })
    } catch (e) {
      setAttachment(null)
      setAttachError(String(e.message || e))
    } finally {
      setAttaching(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  function handleLogout() {
    abortRef.current?.abort()
    logout()
    setConversations([])
    setMessages([])
    setActiveId(null)
    setFocusItem(null)
    setAttachment(null)
    setAttachError(null)
    setInventory(null)
    setAuthState('anonymous')
  }

  if (authState === null) {
    return <div className="boot-screen muted">Loading…</div>
  }
  if (authState === 'anonymous') {
    return (
      <Login
        onSuccess={() => setAuthState('authed')}
        passwordLogin={!!health?.password_login}
        error={authError}
      />
    )
  }

  const appClass = [
    'app',
    launch.embed ? 'app-embed' : '',
    panelOpen ? '' : 'panel-collapsed',
    historyOpen ? '' : 'history-collapsed',
  ]
    .filter(Boolean)
    .join(' ')

  return (
    <div className={appClass}>
      <div className="panel-shell">
        <InventoryPanel
          inventory={inventory}
          error={invError}
          sharesContracts={sharesContracts}
          onSelect={handleSelectSoftware}
          activeId={focusItem?.id}
        />
      </div>
      <div className="panel-backdrop" onClick={() => setPanelOpen(false)} />

      <main className="chat">
        <header>
          <button
            className="panel-toggle"
            onClick={() => setPanelOpen((o) => !o)}
            title={panelOpen ? 'Hide contracts' : 'Show contracts'}
            aria-label={panelOpen ? 'Hide contracts' : 'Show contracts'}
          >
            {panelOpen ? '⟨' : '☰'}
          </button>
          <div className="chat-title">
            <h1>LC DealMate</h1>
            <p className="muted small">
              {sharesContracts
                ? 'Active, expired, or no contract selected — ask here. Read-only; PDFs are never changed.'
                : 'Ask about pricing or a new service. Contract data is not sent to the AI.'}
            </p>
          </div>
          {authState === 'authed' && !launch.embed && (
            <button className="panel-toggle" onClick={handleLogout} title="Sign out" aria-label="Sign out">
              ⏻
            </button>
          )}
          <button
            className="panel-toggle"
            onClick={() => setHistoryOpen((o) => !o)}
            title={historyOpen ? 'Hide chats' : 'Show chats'}
            aria-label={historyOpen ? 'Hide chats' : 'Show chats'}
          >
            {historyOpen ? '⟩' : '🗨'}
          </button>
        </header>

        <div className="thread" ref={threadRef} onScroll={handleThreadScroll}>
          {focusItem && (
            <SoftwareDashboard
              item={focusItem}
              currency={inventory?.currency}
              onBack={() => startNewChat()}
            />
          )}

          {messages.length === 0 && (
            <div className="empty">
              <p className="muted">
                {focusItem
                  ? 'Ask about this contract, compare vendors, or research a new service. The AI cannot change the PDF.'
                  : 'Ask about the portfolio, attach a file, or research a service you do not have yet.'}
              </p>
              {suggestionGroups.map((g) => (
                <SuggestionGroup key={g.label} label={g.label} items={g.items} onPick={send} />
              ))}
            </div>
          )}
          {messages.map((m, i) => (
            <Message key={i} msg={m} />
          ))}
        </div>

        <div className="composer-wrap">
          {attachment && (
            <div className="attach-chip">
              <span title={attachment.filename}>{attachment.filename}</span>
              <button type="button" onClick={() => setAttachment(null)} aria-label="Remove attachment">
                ×
              </button>
            </div>
          )}
          {attachError && <p className="attachment-error">{attachError}</p>}
          <form
            className="composer"
            onSubmit={(e) => {
              e.preventDefault()
              send(input)
            }}
          >
            <input
              ref={fileRef}
              type="file"
              accept=".pdf,.docx,.xlsx,.jpg,.jpeg,.png,.webp,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,image/jpeg,image/png,image/webp"
              hidden
              onChange={(e) => handleAttach(e.target.files?.[0])}
            />
            <textarea
              value={input}
              placeholder={placeholder}
              rows={2}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  send(input)
                }
              }}
            />
            <button
              type="button"
              className="attach-btn"
              disabled={busy || attaching}
              title="Attach PDF, Word, Excel, or image"
              aria-label="Attach a file"
              onClick={() => fileRef.current?.click()}
            >
              {attaching ? 'Uploading…' : 'Attach file'}
            </button>
            {busy ? (
              <button type="button" className="stop" onClick={() => abortRef.current?.abort()}>
                Stop
              </button>
            ) : (
              <button type="submit" disabled={!input.trim()}>
                Ask
              </button>
            )}
          </form>
        </div>
      </main>

      <div className="history-backdrop" onClick={() => setHistoryOpen(false)} />
      <div className="history-shell">
        <ChatHistoryPanel
          conversations={conversations}
          activeId={activeId}
          softwareById={softwareById}
          onSelect={openConversation}
          onNew={() => startNewChat()}
          onDelete={handleDeleteConversation}
          onRename={handleRenameConversation}
        />
      </div>
    </div>
  )
}
