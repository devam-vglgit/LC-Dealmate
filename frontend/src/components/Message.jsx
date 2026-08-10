import { useState } from 'react'
import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

function Thinking({ text }) {
  const [open, setOpen] = useState(false)
  if (!text) return null
  return (
    <div className="thinking">
      <button className="thinking-toggle" onClick={() => setOpen(!open)}>
        {open ? '▾' : '▸'} reasoning
      </button>
      {open && <pre className="thinking-body">{text}</pre>}
    </div>
  )
}

function Searches({ queries }) {
  if (!queries?.length) return null

  // Real query text only arrives once the turn ends; until then these are
  // placeholders, so show a single running count instead of N blank chips.
  const known = queries.filter(Boolean)
  if (!known.length) {
    return (
      <div className="searches">
        <span className="chip chip-search">
          🔍 Searching… ({queries.length})
        </span>
      </div>
    )
  }

  return (
    <details className="searches">
      <summary>
        🔍 {known.length} web search{known.length === 1 ? '' : 'es'}
      </summary>
      <ol>
        {known.map((q, i) => (
          <li key={i}>{q}</li>
        ))}
      </ol>
    </details>
  )
}

function Sources({ items }) {
  if (!items?.length) return null
  return (
    <details className="sources">
      <summary>{items.length} source{items.length === 1 ? '' : 's'}</summary>
      <ol>
        {items.map((s) => (
          <li key={s.url}>
            <a href={s.url} target="_blank" rel="noreferrer noopener">
              {s.title}
            </a>
          </li>
        ))}
      </ol>
    </details>
  )
}

export default function Message({ msg }) {
  if (msg.role === 'user') {
    return (
      <div className="msg msg-user">
        <div className="bubble">{msg.content}</div>
      </div>
    )
  }

  return (
    <div className="msg msg-assistant">
      <Thinking text={msg.thinking} />
      <Searches queries={msg.searches} />
      {msg.status && !msg.content && <div className="muted small">{msg.status}</div>}
      {msg.content ? (
        <div className="prose">
          <Markdown remarkPlugins={[remarkGfm]}>{msg.content}</Markdown>
        </div>
      ) : (
        !msg.error && <span className="muted small">…</span>
      )}
      {msg.error && <div className="error">{msg.error}</div>}
      <Sources items={msg.sources} />
    </div>
  )
}
