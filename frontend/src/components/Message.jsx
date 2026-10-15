import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
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

function ExpandableTable({ node: _node, children, ...props }) {
  const [open, setOpen] = useState(false)

  useEffect(() => {
    if (!open) return
    const onKey = (e) => {
      if (e.key === 'Escape') setOpen(false)
    }
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    document.addEventListener('keydown', onKey)
    return () => {
      document.body.style.overflow = prev
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  return (
    <div className="table-frame">
      <div className="table-toolbar">
        <button type="button" className="table-expand-btn" onClick={() => setOpen(true)}>
          Expand table
        </button>
      </div>
      <div className="table-scroll">
        <table {...props}>{children}</table>
      </div>
      {open &&
        createPortal(
          <div className="table-fs" role="dialog" aria-modal="true" aria-label="Full screen table">
            <div className="table-fs-bar">
              <span className="muted small">Full screen</span>
              <button type="button" className="table-fs-back" onClick={() => setOpen(false)}>
                Back to chat
              </button>
            </div>
            <div className="table-fs-body">
              <table {...props}>{children}</table>
            </div>
          </div>,
          document.body,
        )}
    </div>
  )
}

function ExternalLink({ node: _node, href, children, ...props }) {
  const external = /^https?:\/\//i.test(href || '')
  if (!external) {
    return (
      <a href={href} {...props}>
        {children}
      </a>
    )
  }
  return (
    <a href={href} {...props} target="_blank" rel="noopener noreferrer">
      {children}
    </a>
  )
}

function Searches({ queries }) {
  if (!queries?.length) return null
  const known = queries.filter(Boolean)
  if (!known.length) {
    return (
      <div className="searches">
        <span className="chip chip-search">Searching…</span>
      </div>
    )
  }
  return null
}

export default function Message({ msg }) {
  if (msg.role === 'user') {
    return (
      <div className="msg msg-user">
        <div className="bubble">
          {msg.attachment && <div className="bubble-attach">{msg.attachment}</div>}
          {msg.content}
        </div>
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
          <Markdown
            remarkPlugins={[remarkGfm]}
            components={{
              table: ExpandableTable,
              a: ExternalLink,
            }}
          >
            {msg.content}
          </Markdown>
        </div>
      ) : (
        !msg.error && <span className="muted small">…</span>
      )}
      {msg.error && <div className="error">{msg.error}</div>}
    </div>
  )
}
