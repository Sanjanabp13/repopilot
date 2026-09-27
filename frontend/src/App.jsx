import { useState, useEffect, useRef } from 'react'
import mermaid from 'mermaid'

const API = 'http://localhost:8000'

mermaid.initialize({
  startOnLoad:  false,
  theme:        'neutral',
  securityLevel:'loose',
  maxTextSize:  1000000,
  maxEdges:     1000,
})

// ── helpers ──────────────────────────────────────────────────────────────────

async function post(path, body) {
  const r = await fetch(`${API}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!r.ok) {
    const err = await r.json().catch(() => ({ detail: r.statusText }))
    throw new Error(err.detail || r.statusText)
  }
  return r.json()
}

async function get(path) {
  const r = await fetch(`${API}${path}`)
  if (!r.ok) throw new Error(r.statusText)
  return r.json()
}

// ── strip ```mermaid fences + remove front-matter that breaks the parser ─────

function stripFences(raw) {
  return raw
    .trim()
    .replace(/^```mermaid\s*/i, '')
    .replace(/^```\s*/i, '')
    .replace(/\s*```$/, '')
    // strip YAML front-matter block  ---\n...\n---
    .replace(/^---[\s\S]*?---\s*/m, '')
    // strip any stray  "title: …"  lines
    .replace(/^title:.*$/gm, '')
    .trim()
}

// ── simple Markdown → HTML renderer (bold, inline code, bullets, blockquote) ─

function renderMarkdown(text) {
  if (!text) return ''
  return text
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    // code blocks
    .replace(/```[\w]*\n([\s\S]*?)```/g, (_, c) =>
      `<pre class="code-block"><code>${c.trim()}</code></pre>`)
    // inline code
    .replace(/`([^`]+)`/g, '<code class="inline-code">$1</code>')
    // bold
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    // blockquote
    .replace(/^  &gt; (.+)$/gm, '<blockquote>$1</blockquote>')
    // headers
    .replace(/^### (.+)$/gm, '<h4 class="md-h4">$1</h4>')
    .replace(/^## (.+)$/gm, '<h3 class="md-h3">$1</h3>')
    // bullets
    .replace(/^- (.+)$/gm, '<li>$1</li>')
    .replace(/(<li>[\s\S]*?<\/li>(?:\n<li>[\s\S]*?<\/li>)*)/g, '<ul>$1</ul>')
    // newlines
    .replace(/\n{2,}/g, '</p><p>')
    .replace(/\n/g, '<br/>')
}

// ── build nodeId → full FQN map from the diagram source ─────────────────────
// The renderer emits:  click {nid} callback "{full.fqn}"
// We parse that to get a reliable id→fqn lookup so clicks send the FQN.

function buildFqnMap(diagramSource) {
  const map = {}
  const re = /^\s*click\s+(\S+)\s+callback\s+"([^"]+)"/gm
  let m
  while ((m = re.exec(diagramSource)) !== null) {
    map[m[1]] = m[2]   // nid → fqn
  }
  return map
}

// ── Mermaid diagram component ─────────────────────────────────────────────────

function Diagram({ code, onNodeClick, containerRef }) {
  const innerRef = useRef(null)
  const ref      = containerRef || innerRef   // allow parent to own the DOM ref
  const countRef = useRef(0)

  useEffect(() => {
    if (!code || !ref.current) return
    const clean = stripFences(code)
    if (!clean) return
    ref.current.innerHTML = ''
    const id    = `mermaid_${Date.now()}_${++countRef.current}`
    const fqnMap = buildFqnMap(clean)   // nodeId → full FQN

    mermaid.render(id, clean).then(({ svg }) => {
      ref.current.innerHTML = svg
      ref.current.querySelectorAll('.node').forEach(el => {
        el.style.cursor = 'pointer'
        el.addEventListener('click', () => {
          // Mermaid sets the SVG node id as  "flowchart-{nid}-NNN"
          // Extract the nid part and look up the FQN.
          const svgId  = el.id || ''                          // e.g. "flowchart-sample_project_api_get_user-42"
          const parts  = svgId.replace(/^flowchart-/, '').split('-')
          // The nid is everything except the trailing numeric index
          // Try progressively shorter prefixes until we get a fqnMap hit
          let fqn = null
          for (let i = parts.length - 1; i >= 1; i--) {
            const candidate = parts.slice(0, i).join('_')
            if (fqnMap[candidate]) { fqn = fqnMap[candidate]; break }
          }
          // Fallback: also check the full id minus the last "-N" segment
          if (!fqn) {
            const noSuffix = svgId.replace(/^flowchart-/, '').replace(/-\d+$/, '')
            fqn = fqnMap[noSuffix] || null
          }
          // Last resort: use the visible label text
          if (!fqn) {
            fqn = el.querySelector('span,text')?.textContent?.trim() || null
          }
          if (fqn && onNodeClick) onNodeClick(fqn)
        })
      })
    }).catch(err => {
      console.error('Mermaid render error:', err)
      ref.current.innerHTML =
        `<pre class="mermaid-error">Diagram error: ${err.message}\n\n${clean.slice(0, 300)}</pre>`
    })
  }, [code])

  return <div ref={ref} className="diagram-container" />
}

// ── main app ──────────────────────────────────────────────────────────────────

export default function App() {
  const [source, setSource]           = useState('tests/fixtures/sample_project')
  const [session, setSession]         = useState(null)
  const [stats, setStats]             = useState(null)
  const [diagram, setDiagram]         = useState('')
  const [diagramKind, setDiagramKind] = useState('call_graph')
  const [impact, setImpact]           = useState(null)
  const [chat, setChat]               = useState([])
  const [question, setQuestion]       = useState('')
  const [status, setStatus]           = useState('')
  const [statusOk, setStatusOk]       = useState(true)
  const [busy, setBusy]               = useState(false)
  const [onboarding, setOnboarding]   = useState('')
  const [serverOk, setServerOk]       = useState(null)
  const chatEndRef   = useRef(null)
  const diagramRef   = useRef(null)    // ref to the diagram container DOM node

  // Server health ping
  useEffect(() => {
    fetch(`${API}/health`)
      .then(r => setServerOk(r.ok))
      .catch(() => setServerOk(false))
  }, [])

  // Auto-scroll chat
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [chat])

  function setMsg(msg, ok = true) { setStatus(msg); setStatusOk(ok) }

  // ── analyze ────────────────────────────────────────────────────────────────

  async function handleAnalyze() {
    setBusy(true); setMsg('Analyzing repository…'); setDiagram(''); setImpact(null)
    try {
      const res = await post('/analyze', { source, languages: ['python'] })
      setSession(res.analysis_id)
      setStats(res)
      setMsg(`✓ ${res.total_symbols} symbols indexed — ${res.parse_errors} parse errors`)
      await loadDiagram(res.analysis_id, diagramKind)
    } catch (e) {
      setMsg(`✗ ${e.message}`, false)
    } finally {
      setBusy(false)
    }
  }

  // ── diagram ────────────────────────────────────────────────────────────────

  async function loadDiagram(sid, kind) {
    try {
      const res = await get(`/diagram?analysis_id=${sid}&kind=${kind}`)
      setDiagram(res.diagram)
    } catch (e) {
      setMsg(`Diagram error: ${e.message}`, false)
    }
  }

  async function switchDiagram(kind) {
    if (!session) return
    // Clear focus state when switching tabs
    setImpact(null)
    setDiagramKind(kind)
    if (diagramRef.current) diagramRef.current.innerHTML = ''
    await loadDiagram(session, kind)
  }

  // ── node click → impact ────────────────────────────────────────────────────

  async function handleNodeClick(label) {
    if (!session) return
    // Immediately clear canvas so there's no stale diagram while loading
    if (diagramRef.current) diagramRef.current.innerHTML = ''
    setDiagram('')
    setBusy(true); setMsg(`Computing blast radius for: ${label}…`)
    try {
      const res = await post('/impact', { analysis_id: session, symbol_fqn: label })
      setImpact(res)
      setDiagram(res.diagram)
      setMsg(`✓ Blast radius: ${res.total_impact} affected symbols · ${res.affected_tests.length} tests`)
    } catch (e) {
      setMsg(`Impact: ${e.message}`, false)
    } finally {
      setBusy(false)
    }
  }

  // ── reset to full graph ────────────────────────────────────────────────────

  async function handleClearFocus() {
    if (!session) return
    setImpact(null)
    if (diagramRef.current) diagramRef.current.innerHTML = ''
    setDiagram('')
    await loadDiagram(session, diagramKind)
  }

  // ── chat ───────────────────────────────────────────────────────────────────

  async function handleChat(e) {
    e.preventDefault()
    if (!session || !question.trim()) return
    const q = question.trim()
    setQuestion('')
    setChat(c => [...c, { role: 'user', text: q }])
    setBusy(true)
    try {
      const res = await post('/chat', { analysis_id: session, question: q })
      setChat(c => [...c, {
        role:       'assistant',
        text:       res.answer,
        citations:  res.citations,
        confidence: res.confidence,
      }])
    } catch (e) {
      setChat(c => [...c, { role: 'assistant', text: `**Error:** ${e.message}`, citations: [] }])
    } finally {
      setBusy(false)
    }
  }

  // ── export ─────────────────────────────────────────────────────────────────

  async function handleExport() {
    if (!session) return
    setBusy(true)
    try {
      const res  = await post('/export-onboarding', { analysis_id: session })
      setOnboarding(res.markdown)
      const blob = new Blob([res.markdown], { type: 'text/markdown' })
      const url  = URL.createObjectURL(blob)
      const a    = document.createElement('a')
      a.href = url; a.download = 'ONBOARDING.md'; a.click()
      URL.revokeObjectURL(url)
      setMsg('✓ ONBOARDING.md exported')
    } catch (e) {
      setMsg(`Export error: ${e.message}`, false)
    } finally {
      setBusy(false)
    }
  }

  // ── render ─────────────────────────────────────────────────────────────────

  return (
    <div className="app">

      {/* ── nav header ── */}
      <header className="navbar">
        <div className="navbar-left">
          <span className="logo-badge">RP</span>
          <span className="logo-title">RepoPilot</span>
          <span className="logo-sub">TraceMind</span>
        </div>
        <div className="navbar-right">
          <span className={`server-dot ${serverOk === true ? 'ok' : serverOk === false ? 'err' : 'pending'}`}>●</span>
          <span className="server-label">
            {serverOk === true ? 'Server Ready' : serverOk === false ? 'Server Offline' : 'Connecting…'}
          </span>
        </div>
      </header>

      {/* ── analyze bar ── */}
      <div className="analyze-bar">
        <input
          className="analyze-input"
          value={source}
          onChange={e => setSource(e.target.value)}
          placeholder="Local path or GitHub URL…"
          disabled={busy}
        />
        <button className="btn btn-primary" onClick={handleAnalyze} disabled={busy}>
          {busy ? <span className="spinner">⟳</span> : '⚡ Analyze'}
        </button>
        {session && (
          <button className="btn btn-secondary" onClick={handleExport} disabled={busy}>
            ↓ Export ONBOARDING.md
          </button>
        )}
      </div>

      {/* ── status bar ── */}
      {status && (
        <div className={`status-bar ${statusOk ? 'ok' : 'err'}`}>{status}</div>
      )}

      {/* ── stats strip ── */}
      {stats && (
        <div className="stats-strip">
          <span className="stat"><span className="stat-icon">📦</span>{stats.modules} modules</span>
          <span className="stat"><span className="stat-icon">🔷</span>{stats.classes} classes</span>
          <span className="stat"><span className="stat-icon">⚙️</span>{stats.methods} methods</span>
          <span className="stat"><span className="stat-icon">𝑓</span>{stats.functions} functions</span>
          <span className="stat"><span className="stat-icon">📊</span>{stats.indexed_chunks} chunks indexed</span>
        </div>
      )}

      {/* ── main panels ── */}
      {session && (
        <div className="panels">

          {/* ── left: visualizer ── */}
          <section className="panel panel-viz">
            <div className="panel-header">
              <span className="panel-title">🗺 Visualizer</span>
              <div className="pill-group">
                {[['call_graph', 'Call Graph'], ['dep_graph', 'Dep Graph']].map(([k, label]) => (
                  <button
                    key={k}
                    className={`pill ${diagramKind === k ? 'active' : ''}`}
                    onClick={() => switchDiagram(k)}
                    disabled={busy}
                  >{label}</button>
                ))}
              </div>
            </div>

            {impact && (
              <div className="impact-badge">
                <span className="impact-badge-text">
                  Blast radius: <code>{impact.changed_fqn.split('.').slice(-2).join('.')}</code>
                  {' — '}<strong>{impact.total_impact}</strong> affected
                  {impact.affected_tests.length > 0 && (
                    <span className="test-badge"> · {impact.affected_tests.length} tests 🧪</span>
                  )}
                </span>
                <button className="btn-clear-focus" onClick={handleClearFocus} disabled={busy}>
                  ← Full Graph
                </button>
              </div>
            )}

            <div className="hint">💡 Click any node to compute its blast radius</div>

            {diagram
              ? <Diagram code={diagram} onNodeClick={handleNodeClick} containerRef={diagramRef} />
              : <div className="diagram-empty">Run Analyze to render a diagram</div>
            }
          </section>

          {/* ── right: Q&A ── */}
          <section className="panel panel-chat">
            <div className="panel-header">
              <span className="panel-title">💬 Q&A Assistant</span>
            </div>

            <div className="chat-messages">
              {chat.length === 0 && (
                <div className="chat-empty">Ask anything about the repository…</div>
              )}
              {chat.map((m, i) => (
                <div key={i} className={`bubble bubble-${m.role}`}>
                  {m.role === 'user'
                    ? <p className="bubble-text">{m.text}</p>
                    : <div
                        className="bubble-text md-body"
                        dangerouslySetInnerHTML={{ __html: renderMarkdown(m.text) }}
                      />
                  }
                  {m.citations?.length > 0 && (
                    <div className="citations">
                      {m.citations.slice(0, 3).map((c, j) => (
                        <span key={j} className="citation-chip">
                          📍 <code>{c.file_path.split('/').pop()}:{c.line}</code>
                        </span>
                      ))}
                      <span className="confidence-chip">
                        {Math.round((m.confidence || 0) * 100)}% conf
                      </span>
                    </div>
                  )}
                </div>
              ))}
              <div ref={chatEndRef} />
            </div>

            <form className="chat-form" onSubmit={handleChat}>
              <input
                className="chat-input"
                value={question}
                onChange={e => setQuestion(e.target.value)}
                placeholder="e.g. What does get_user do?"
                disabled={busy}
              />
              <button
                type="submit"
                className="btn btn-primary"
                disabled={busy || !question.trim()}
              >Send</button>
            </form>
          </section>
        </div>
      )}

      {/* ── onboarding preview ── */}
      {onboarding && (
        <details className="onboarding-preview">
          <summary>Preview ONBOARDING.md</summary>
          <pre>{onboarding}</pre>
        </details>
      )}
    </div>
  )
}
