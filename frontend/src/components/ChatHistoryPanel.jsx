function relativeTime(iso) {
  if (!iso) return ''
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return ''
  const mins = Math.floor((Date.now() - then) / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  const days = Math.floor(hrs / 24)
  if (days < 7) return `${days}d ago`
  return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

export default function ChatHistoryPanel({
  conversations,
  activeId,
  softwareById,
  onSelect,
  onNew,
  onDelete,
  onRename,
}) {
  return (
    <aside className="history">
      <div className="panel-head">
        <h2>Chats</h2>
        <button className="add-btn" onClick={onNew} title="New chat">
          +
        </button>
      </div>

      <button className="new-chat-btn" onClick={onNew}>
        + New chat
      </button>

      {conversations.length === 0 ? (
        <p className="muted small">No conversations yet. Ask something to start one.</p>
      ) : (
        <ul className="conv-list">
          {conversations.map((c) => {
            const software = c.focus_id ? softwareById[c.focus_id] : null
            return (
              <li
                key={c.id}
                className={`conv-item${c.id === activeId ? ' conv-item-active' : ''}`}
              >
                <button className="conv-open" onClick={() => onSelect(c.id)} title={c.title}>
                  <span className="conv-title">{c.title}</span>
                  <span className="conv-meta">
                    {software && <span className="conv-tag">{software.product}</span>}
                    <span className="muted">{relativeTime(c.updated_at)}</span>
                  </span>
                </button>
                <span className="conv-actions">
                  <button
                    className="remove-btn"
                    title="Rename"
                    onClick={() => onRename(c.id, c.title)}
                  >
                    ✎
                  </button>
                  <button
                    className="remove-btn"
                    title="Delete chat"
                    onClick={() => onDelete(c.id, c.title)}
                  >
                    ×
                  </button>
                </span>
              </li>
            )
          })}
        </ul>
      )}
    </aside>
  )
}
