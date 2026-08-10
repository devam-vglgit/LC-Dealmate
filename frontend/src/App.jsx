import { useEffect, useMemo, useRef, useState } from 'react'
import {
  deleteConversation,
  deleteSoftware,
  fetchHealth,
  fetchInventory,
  getConversation,
  getToken,
  listConversations,
  logout,
  renameConversation,
  setUnauthorizedHandler,
  streamChat,
} from './api'
import Login from './components/Login'
import InventoryPanel from './components/InventoryPanel'
import ChatHistoryPanel from './components/ChatHistoryPanel'
import AddSoftwareModal from './components/AddSoftwareModal'
import SoftwareDashboard from './components/SoftwareDashboard'
import TokenMeter from './components/TokenMeter'
import Message from './components/Message'

// The API reports output tokens only once, when a message ends. To keep the meter
// moving during a long answer we estimate from streamed characters (~4 chars per
// token for English prose) and snap to the exact figure when it arrives.
const CHARS_PER_TOKEN = 4

const GENERAL_SUGGESTIONS = [
  'What are we overpaying for right now?',
  'Which contracts renew in the next 90 days, and what should we ask for?',
  'Where is our software spend concentrated?',
  'Which of our tools overlap with each other?',
]

function suggestionsFor(item) {
  return [
    `Should we renew ${item.product} or switch to a competitor?`,
    `Benchmark ${item.product} against competitor pricing at our seat count.`,
    `What leverage do we have going into the ${item.product} renewal?`,
    `Are we using ${item.product} enough to justify the cost?`,
  ]
}

export default function App() {
  // null = still checking whether this server even requires a login.
  const [authState, setAuthState] = useState(null)
  const [inventory, setInventory] = useState(null)
  const [invError, setInvError] = useState(null)
  const [showAddModal, setShowAddModal] = useState(false)
  const [focusItem, setFocusItem] = useState(null)

  const [panelOpen, setPanelOpen] = useState(true)
  const [historyOpen, setHistoryOpen] = useState(true)

  const [conversations, setConversations] = useState([])
  const [activeId, setActiveId] = useState(null)
  const [messages, setMessages] = useState([])

  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [usage, setUsage] = useState(null)
  const abortRef = useRef(null)
  const threadRef = useRef(null)
  // Characters streamed this turn, for the live output estimate.
  const streamedCharsRef = useRef(0)
  // Whether the reader is following the tail. Once they scroll up to re-read
  // something, auto-scroll stops fighting them until they come back down.
  const pinnedRef = useRef(true)

  const softwareById = useMemo(() => {
    const map = {}
    for (const s of inventory?.software || []) map[s.id] = s
    return map
  }, [inventory])

  // Decide up front whether a login is needed, and bounce back to it if a
  // session expires mid-use.
  useEffect(() => {
    setUnauthorizedHandler(() => setAuthState('anonymous'))
    fetchHealth()
      .then((h) => {
        if (!h.auth_required) return setAuthState('open')
        setAuthState(getToken() ? 'authed' : 'anonymous')
      })
      .catch(() => {
        setAuthState('anonymous')
        setInvError('Could not reach the API. Is the backend running?')
      })
  }, [])

  // On open: restore the stack and the most recent conversation, so the portal
  // comes back exactly where it was left.
  useEffect(() => {
    if (authState !== 'authed' && authState !== 'open') return

    fetchInventory()
      .then(setInventory)
      .catch(() => setInvError('Could not reach the API. Is the backend running?'))

    listConversations()
      .then(async (list) => {
        setConversations(list)
        if (list.length) await openConversation(list[0].id, list)
      })
      .catch(() => {})
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authState])

  // Scroll the thread element itself rather than calling scrollIntoView on a
  // marker: scrollIntoView walks up and scrolls *every* scrollable ancestor, so
  // during streaming it dragged the whole layout (sidebars included) downward on
  // each token. Setting scrollTop is instant and strictly local to this element.
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
      // Show the last turn's stored counts rather than a stale number from
      // whatever chat was open before.
      const lastUsage = [...msgs].reverse().find((m) => m.usage)?.usage
      setUsage(lastUsage ? { ...lastUsage, exact: true } : null)
      const list = listOverride || conversations
      const focusId = conv.focus_id
      if (focusId) {
        // Inventory may still be loading on first paint; fall back to a lookup
        // against whatever we have, and let the effect below fill it in.
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

  // If a conversation was restored before the inventory arrived, resolve its
  // focused software once the inventory lands.
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
    setUsage(null)
    setFocusItem(focus)
  }

  async function send(text) {
    const question = text.trim()
    if (!question || busy) return

    const conversationId = activeId
    const focusId = focusItem?.id || null

    setMessages((prev) => [
      ...prev,
      { role: 'user', content: question },
      { role: 'assistant', content: '', searches: [] },
    ])
    setInput('')
    setBusy(true)
    pinnedRef.current = true // asking something re-attaches you to the tail
    streamedCharsRef.current = 0
    setUsage({ input_tokens: 0, output_tokens: 0, cache_read_input_tokens: 0, exact: false })

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
        { message: question, conversationId, focusId },
        (ev) => {
          switch (ev.type) {
            case 'conversation':
              // The server may have just created this conversation — adopt its id
              // so the next message continues the same thread.
              setActiveId(ev.id)
              return
            case 'text':
              streamedCharsRef.current += ev.text.length
              setUsage((u) =>
                u?.exact
                  ? u
                  : {
                      ...(u || {}),
                      output_tokens: Math.round(streamedCharsRef.current / CHARS_PER_TOKEN),
                      exact: false,
                    },
              )
              return patch((m) => ({ ...m, content: m.content + ev.text }))
            case 'thinking':
              streamedCharsRef.current += ev.text.length
              return patch((m) => ({ ...m, thinking: (m.thinking || '') + ev.text }))
            case 'usage':
              // Server figures are authoritative. Input/cache are exact as soon as
              // they arrive; output is exact only on the final event.
              return setUsage((u) => ({
                input_tokens: ev.input_tokens,
                cache_read_input_tokens: ev.cache_read_input_tokens,
                output_tokens: ev.final
                  ? ev.output_tokens
                  : Math.max(ev.output_tokens, u?.output_tokens || 0),
                exact: !!ev.final,
              }))
            case 'search_start':
              return patch((m) => ({ ...m, searches: [...(m.searches || []), null] }))
            case 'searches':
              // Real queries arrive after the turn — replace the placeholders.
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

  async function handleDeleteSoftware(id, name) {
    if (!window.confirm(`Remove ${name} from the stack?`)) return
    try {
      const next = await deleteSoftware(id)
      setInventory(next)
      if (focusItem?.id === id) setFocusItem(null)
    } catch (e) {
      setInvError(String(e.message || e))
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

  // Clicking a line item resumes its most recent chat, or starts a fresh one
  // scoped to it if there isn't one yet.
  function handleSelectSoftware(item) {
    const existing = conversations.find((c) => c.focus_id === item.id)
    if (existing) {
      openConversation(existing.id)
      setFocusItem(item)
    } else {
      startNewChat(item)
    }
  }

  const suggestions = focusItem ? suggestionsFor(focusItem) : GENERAL_SUGGESTIONS
  const placeholder = focusItem
    ? `Ask about ${focusItem.product}…`
    : 'Ask about a vendor, a renewal, or the whole stack…'

  function handleLogout() {
    abortRef.current?.abort()
    logout()
    setConversations([])
    setMessages([])
    setActiveId(null)
    setUsage(null)
    setFocusItem(null)
    setInventory(null)
    setAuthState('anonymous')
  }

  if (authState === null) {
    return <div className="boot-screen muted">Loading…</div>
  }
  if (authState === 'anonymous') {
    return <Login onSuccess={() => setAuthState('authed')} />
  }

  const appClass = [
    'app',
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
          onAddClick={() => setShowAddModal(true)}
          onDelete={handleDeleteSoftware}
          onSelect={handleSelectSoftware}
          activeId={focusItem?.id}
        />
      </div>
      <div className="panel-backdrop" onClick={() => setPanelOpen(false)} />
      {showAddModal && (
        <AddSoftwareModal onClose={() => setShowAddModal(false)} onAdded={setInventory} />
      )}

      <main className="chat">
        <header>
          <button
            className="panel-toggle"
            onClick={() => setPanelOpen((o) => !o)}
            title={panelOpen ? 'Hide current stack' : 'Show current stack'}
            aria-label={panelOpen ? 'Hide current stack' : 'Show current stack'}
          >
            {panelOpen ? '⟨' : '☰'}
          </button>
          <div className="chat-title">
            <h1>LC DealMate</h1>
            <p className="muted small">
              Benchmarks your software spend against live competitor pricing.
            </p>
          </div>
          <TokenMeter usage={usage} streaming={busy} />
          {authState === 'authed' && (
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
                  ? `Ask about ${focusItem.product}, or use one of these:`
                  : 'Ask about a vendor, a renewal, or the whole stack.'}
              </p>
              <div className="suggestions">
                {suggestions.map((s) => (
                  <button key={s} onClick={() => send(s)}>
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}
          {messages.map((m, i) => (
            <Message key={i} msg={m} />
          ))}
        </div>

        <form
          className="composer"
          onSubmit={(e) => {
            e.preventDefault()
            send(input)
          }}
        >
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
