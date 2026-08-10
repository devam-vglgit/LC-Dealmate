const n = (v) => new Intl.NumberFormat('en-US').format(Math.max(0, Math.round(v || 0)))

export default function TokenMeter({ usage, streaming }) {
  if (!usage) return null

  const { input_tokens, output_tokens, cache_read_input_tokens, exact } = usage
  const approx = streaming && !exact

  const title = [
    `Input: ${n(input_tokens)} tokens (exact)`,
    cache_read_input_tokens
      ? `Cached: ${n(cache_read_input_tokens)} tokens, re-read at ~10% cost`
      : null,
    approx
      ? `Streamed so far: ~${n(output_tokens)} tokens, estimated from the text on screen.\n` +
        'Billed output will be higher — it also counts internal reasoning tokens, which\n' +
        'are never sent to the browser. The exact figure lands when the answer finishes.'
      : `Output: ${n(output_tokens)} tokens (exact, billed — includes internal reasoning)`,
  ]
    .filter(Boolean)
    .join('\n')

  return (
    <span className={`token-meter${approx ? ' token-meter-approx' : ''}`} title={title}>
      <span className="tm-dot" />
      <span>
        {approx ? `~${n(output_tokens)} streamed` : `${n(output_tokens)} out`}
      </span>
      <span className="tm-sep">·</span>
      <span>{n(input_tokens)} in</span>
      {cache_read_input_tokens > 0 && (
        <>
          <span className="tm-sep">·</span>
          <span className="tm-cache">{n(cache_read_input_tokens)} cached</span>
        </>
      )}
    </span>
  )
}
