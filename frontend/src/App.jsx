import { useState, useEffect, useRef, useCallback } from 'react'
import mermaid from 'mermaid'

const API = 'http://localhost:8000'

// ── Initialize Mermaid with clean spacing & dark palette ──────────────────────
mermaid.initialize({
  startOnLoad: false,
  theme: 'dark',
  securityLevel: 'loose',
  maxTextSize: 1000000,
  maxEdges: 1200,
  flowchart: {
    curve: 'basis',
    nodeSpacing: 50,
    rankSpacing: 65,
    padding: 16,
    useMaxWidth: false,
    htmlLabels: true,
  },
})

// ── HTTP API helpers ─────────────────────────────────────────────────────────

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

// ── Strip ```mermaid fences & title headers ───────────────────────────────────

function stripFences(raw) {
  if (!raw) return ''
  return raw
    .trim()
    .replace(/^```mermaid\s*/i, '')
    .replace(/^```\s*/i, '')
    .replace(/\s*```$/, '')
    .replace(/^---[\s\S]*?---\s*/m, '')
    .replace(/^title:.*$/gm, '')
    .trim()
}

// ── Markdown → HTML formatter ────────────────────────────────────────────────

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
    .replace(/^&gt; (.+)$/gm, '<blockquote>$1</blockquote>')
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

// ── Parse Mermaid click callbacks to build nodeId → full FQN map ─────────────

function buildFqnMap(diagramSource) {
  const map = {}
  const re = /^\s*click\s+(\S+)\s+callback\s+"([^"]+)"/gm
  let m
  while ((m = re.exec(diagramSource)) !== null) {
    map[m[1]] = m[2]
  }
  return map
}

function fqnToId(fqn) {
  return fqn.replace(/[^A-Za-z0-9_]/g, '_')
}

// ── Diagram Component with In-Place Blast Radius Highlighting ─────────────────

function Diagram({ code, onNodeClick, impact, containerRef }) {
  const innerRef = useRef(null)
  const ref = containerRef || innerRef
  const countRef = useRef(0)
  const fqnMapRef = useRef({})

  // 1. Render Diagram SVG
  useEffect(() => {
    if (!code || !ref.current) return
    const clean = stripFences(code)
    if (!clean) return

    ref.current.innerHTML = ''
    const id = `mermaid_${Date.now()}_${++countRef.current}`
    const fqnMap = buildFqnMap(clean)
    fqnMapRef.current = fqnMap

    mermaid.render(id, clean).then(({ svg }) => {
      if (!ref.current) return
      ref.current.innerHTML = svg
      const svgEl = ref.current.querySelector('svg')
      if (!svgEl) return

      // Make SVG nodes clickable
      svgEl.querySelectorAll('.node').forEach(el => {
        el.style.cursor = 'pointer'
        el.addEventListener('click', (e) => {
          e.stopPropagation()
          const svgId = el.id || ''
          const parts = svgId.replace(/^flowchart-/, '').split('-')

          // Extract candidate nodeId
          let fqn = null
          for (let i = parts.length - 1; i >= 1; i--) {
            const candidate = parts.slice(0, i).join('-')
            if (fqnMap[candidate]) { fqn = fqnMap[candidate]; break }
            const candidateUnderscore = parts.slice(0, i).join('_')
            if (fqnMap[candidateUnderscore]) { fqn = fqnMap[candidateUnderscore]; break }
          }

          if (!fqn) {
            const noSuffix = svgId.replace(/^flowchart-/, '').replace(/-\d+$/, '')
            fqn = fqnMap[noSuffix] || null
          }

          if (!fqn) {
            fqn = el.querySelector('span, text')?.textContent?.trim() || null
          }

          if (fqn && onNodeClick) {
            onNodeClick(fqn)
          }
        })
      })

      // Re-apply blast radius highlight if active
      applyBlastRadius(ref.current, impact, fqnMap)
    }).catch(err => {
      console.error('Mermaid render error:', err)
      if (ref.current) {
        ref.current.innerHTML =
          `<pre class="mermaid-error">Diagram render error: ${err.message}\n\n${clean.slice(0, 300)}</pre>`
      }
    })
  }, [code])

  // 2. React to Impact changes without replacing the entire graph
  useEffect(() => {
    if (!ref.current) return
    applyBlastRadius(ref.current, impact, fqnMapRef.current)
  }, [impact])

  return <div ref={ref} className="diagram-container" />
}

// ── In-Place Blast Radius Highlighting Logic (Requirement 3) ───────────────────

function applyBlastRadius(container, impact, fqnMap) {
  if (!container) return
  const svg = container.querySelector('svg')
  if (!svg) return

  // Reset any previous highlight classes
  svg.classList.remove('graph-blast-active')
  svg.querySelectorAll('.node').forEach(n => {
    n.classList.remove('node-target', 'node-direct', 'node-transitive', 'node-test', 'node-dimmed')
    // Remove test badge icon if present
    const testIcon = n.querySelector('.test-icon-badge')
    if (testIcon) testIcon.remove()
  })
  svg.querySelectorAll('.edgePath').forEach(e => {
    e.classList.remove('edge-highlighted', 'edge-dimmed')
  })

  // If no blast radius selected, stay in normal full graph view
  if (!impact) return

  svg.classList.add('graph-blast-active')

  const targetFqn = impact.changed_fqn || ''
  const targetId = fqnToId(targetFqn)
  const targetSimple = targetFqn.split('.').pop()

  const directFqns = new Set((impact.direct_callers || []).map(s => s.fqn))
  const directSimples = new Set((impact.direct_callers || []).map(s => s.name || s.fqn.split('.').pop()))
  const directIds = new Set((impact.direct_callers || []).map(s => fqnToId(s.fqn)))

  const transitiveFqns = new Set((impact.transitive_callers || []).map(s => s.fqn))
  const transitiveSimples = new Set((impact.transitive_callers || []).map(s => s.name || s.fqn.split('.').pop()))
  const transitiveIds = new Set((impact.transitive_callers || []).map(s => fqnToId(s.fqn)))

  const testFqns = new Set((impact.affected_tests || []).map(s => s.fqn))
  const testSimples = new Set((impact.affected_tests || []).map(s => s.name || s.fqn.split('.').pop()))
  const testIds = new Set((impact.affected_tests || []).map(s => fqnToId(s.fqn)))

  const blastIds = new Set([targetId, ...directIds, ...transitiveIds, ...testIds])

  svg.querySelectorAll('.node').forEach(nodeEl => {
    const svgId = nodeEl.id || ''
    const rawId = svgId.replace(/^flowchart-/, '').replace(/-\d+$/, '')
    const fqn = fqnMap[rawId] || ''
    const textLabel = nodeEl.querySelector('span, text')?.textContent?.trim() || ''

    const isTarget = fqn === targetFqn || rawId === targetId || textLabel === targetSimple
    const isTest = testFqns.has(fqn) || testIds.has(rawId) || testSimples.has(textLabel)
    const isDirect = directFqns.has(fqn) || directIds.has(rawId) || directSimples.has(textLabel)
    const isTransitive = transitiveFqns.has(fqn) || transitiveIds.has(rawId) || transitiveSimples.has(textLabel)

    if (isTarget) {
      nodeEl.classList.add('node-target')
    } else if (isTest) {
      nodeEl.classList.add('node-test')
      // Append small test icon indicator 🧪
      const label = nodeEl.querySelector('.label')
      if (label && !label.querySelector('.test-icon-badge')) {
        const badge = document.createElementNS('http://www.w3.org/2000/svg', 'text')
        badge.setAttribute('class', 'test-icon-badge')
        badge.setAttribute('y', '-6')
        badge.setAttribute('x', '0')
        badge.textContent = '🧪'
        label.appendChild(badge)
      }
    } else if (isDirect) {
      nodeEl.classList.add('node-direct')
    } else if (isTransitive) {
      nodeEl.classList.add('node-transitive')
    } else {
      nodeEl.classList.add('node-dimmed')
    }
  })

  // Highlight connecting edges, dim others
  svg.querySelectorAll('.edgePath').forEach(edgeEl => {
    const classes = edgeEl.getAttribute('class') || ''
    const match = /LS-(\S+)\s+LE-(\S+)/.exec(classes)
    if (match) {
      const src = match[1]
      const dst = match[2]
      if (blastIds.has(src) && blastIds.has(dst)) {
        edgeEl.classList.add('edge-highlighted')
        return
      }
    }
    edgeEl.classList.add('edge-dimmed')
  })
}

// ── Main RepoPilot Application ────────────────────────────────────────────────

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

  const chatEndRef = useRef(null)
  const diagramRef = useRef(null)

  // Server health ping
  useEffect(() => {
    const checkServer = () => {
      fetch(`${API}/health`)
        .then(r => setServerOk(r.ok))
        .catch(() => setServerOk(false))
    }
    checkServer()
    const timer = setInterval(checkServer, 15000)
    return () => clearInterval(timer)
  }, [])

  // Auto-scroll chat
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [chat])

  function setMsg(msg, ok = true) {
    setStatus(msg)
    setStatusOk(ok)
  }

  // ── 1. Analyze repository (supports local path or GitHub URL) ───────────────

  async function handleAnalyze() {
    if (!source.trim()) return
    setBusy(true)
    setMsg('Analyzing repository (parsing AST, building call graph & RAG embeddings)…')
    setImpact(null)

    try {
      const res = await post('/analyze', {
        source: source.trim(),
        languages: ['python'],
      })
      setSession(res.analysis_id)
      setStats(res)
      setMsg(`✓ Indexed ${res.total_symbols} symbols in ${res.modules} modules with ${res.parse_errors} parse errors`)
      await loadDiagram(res.analysis_id, diagramKind)
    } catch (e) {
      setMsg(`✗ Analysis error: ${e.message}`, false)
    } finally {
      setBusy(false)
    }
  }

  // ── Load full diagram (call graph or dependency graph) ───────────────────────

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
    setImpact(null)
    setDiagramKind(kind)
    await loadDiagram(session, kind)
  }

  // ── 2 & 3. Node click → compute & highlight blast radius in-place ───────────

  const handleNodeClick = useCallback(async (label) => {
    if (!session) return
    setBusy(true)
    setMsg(`Computing blast radius for: ${label}…`)
    try {
      const res = await post('/impact', {
        analysis_id: session,
        symbol_fqn: label,
      })
      setImpact(res)
      const testsCount = res.affected_tests?.length || 0
      setMsg(`✓ Blast radius: ${res.total_impact} affected symbols (${res.direct_callers.length} direct, ${testsCount} tests)`)
    } catch (e) {
      setMsg(`Impact error: ${e.message}`, false)
    } finally {
      setBusy(false)
    }
  }, [session])

  // ── Clear blast radius highlight and return to normal full graph ───────────

  function handleClearFocus() {
    setImpact(null)
    setMsg('Returned to full call graph view')
  }

  // ── 4. Q&A Assistant Chat ───────────────────────────────────────────────────

  async function handleChat(e) {
    if (e) e.preventDefault()
    if (!session || !question.trim() || busy) return
    const q = question.trim()
    setQuestion('')
    setChat(prev => [...prev, { role: 'user', text: q }])
    setBusy(true)

    try {
      const res = await post('/chat', {
        analysis_id: session,
        question: q,
      })
      setChat(prev => [...prev, {
        role:       'assistant',
        text:       res.answer,
        citations:  res.citations || [],
        confidence: res.confidence || 0,
      }])
    } catch (e) {
      setChat(prev => [...prev, {
        role:      'assistant',
        text:      `**Error querying assistant:** ${e.message}`,
        citations: [],
      }])
    } finally {
      setBusy(false)
    }
  }

  function handleSuggestedQuestion(promptText) {
    setQuestion(promptText)
  }

  // ── Export ONBOARDING.md ────────────────────────────────────────────────────

  async function handleExport() {
    if (!session) return
    setBusy(true)
    try {
      const res = await post('/export-onboarding', { analysis_id: session })
      setOnboarding(res.markdown)
      const blob = new Blob([res.markdown], { type: 'text/markdown' })
      const url  = URL.createObjectURL(blob)
      const a    = document.createElement('a')
      a.href = url
      a.download = 'ONBOARDING.md'
      a.click()
      URL.revokeObjectURL(url)
      setMsg('✓ ONBOARDING.md generated and downloaded successfully')
    } catch (e) {
      setMsg(`Export error: ${e.message}`, false)
    } finally {
      setBusy(false)
    }
  }

  // ── Render ──────────────────────────────────────────────────────────────────

  return (
    <div className="app">

      {/* ── Top Header Bar ── */}
      <header className="navbar">
        <div className="navbar-left">
          <span className="logo-badge">RP</span>
          <span className="logo-title">RepoPilot</span>
          <span className="logo-sub">AI Onboarding & Blast Radius</span>
        </div>
        <div className="navbar-right">
          <div className="server-badge">
            <span className={`server-dot ${serverOk === true ? 'ok' : serverOk === false ? 'err' : 'pending'}`} />
            <span>
              {serverOk === true ? 'Server Ready' : serverOk === false ? 'Backend Offline' : 'Connecting…'}
            </span>
          </div>
        </div>
      </header>

      {/* ── 1. Input Section ── */}
      <section className="analyze-bar">
        <div className="input-row">
          <div className="analyze-input-wrap">
            <span className="input-icon">📁</span>
            <input
              className="analyze-input"
              value={source}
              onChange={e => setSource(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') handleAnalyze() }}
              placeholder="Enter GitHub URL (e.g., https://github.com/org/repo) or local repo path..."
              disabled={busy}
            />
          </div>
          <button
            className="btn btn-primary"
            onClick={handleAnalyze}
            disabled={busy || !source.trim()}
          >
            {busy ? <><span className="spinner">⟳</span> Analyzing…</> : '⚡ Analyze Repository'}
          </button>
          {session && (
            <button
              className="btn btn-secondary"
              onClick={handleExport}
              disabled={busy}
            >
              ↓ Export ONBOARDING.md
            </button>
          )}
        </div>

        {/* Quick presets */}
        <div className="preset-chips">
          <span>Quick paths:</span>
          <button
            className="preset-chip"
            onClick={() => setSource('tests/fixtures/sample_project')}
          >
            tests/fixtures/sample_project
          </button>
          <button
            className="preset-chip"
            onClick={() => setSource('.')}
          >
            . (RepoPilot Root)
          </button>
        </div>
      </section>

      {/* ── Status Message Strip ── */}
      {status && (
        <div className={`status-bar ${statusOk ? 'ok' : 'err'}`}>
          {status}
        </div>
      )}

      {/* ── Summary Stats Strip ── */}
      {stats && (
        <div className="stats-strip">
          <div className="stat-item">
            <span className="stat-dot cyan" />
            <span>Modules: <strong>{stats.modules}</strong></span>
          </div>
          <div className="stat-item">
            <span className="stat-dot violet" />
            <span>Classes: <strong>{stats.classes}</strong></span>
          </div>
          <div className="stat-item">
            <span className="stat-dot emerald" />
            <span>Methods: <strong>{stats.methods}</strong></span>
          </div>
          <div className="stat-item">
            <span className="stat-dot amber" />
            <span>Functions: <strong>{stats.functions}</strong></span>
          </div>
          <div className="stat-item">
            <span>Chunks Indexed: <strong>{stats.indexed_chunks}</strong></span>
          </div>
          {stats.parse_errors > 0 && (
            <div className="stat-item" style={{ color: '#f87171' }}>
              <span>Parse Errors: <strong>{stats.parse_errors}</strong></span>
            </div>
          )}
        </div>
      )}

      {/* ── Main Two-Column Viewport ── */}
      {session && (
        <div className="panels">

          {/* ── Left Column: 2. Graph View & 3. Blast Radius ── */}
          <section className="panel panel-viz">
            <div className="panel-header">
              <span className="panel-title">
                <span>🗺</span> Architecture Visualizer
              </span>
              <div className="pill-group">
                <button
                  className={`pill ${diagramKind === 'call_graph' ? 'active' : ''}`}
                  onClick={() => switchDiagram('call_graph')}
                  disabled={busy}
                >
                  Call Graph
                </button>
                <button
                  className={`pill ${diagramKind === 'dep_graph' ? 'active' : ''}`}
                  onClick={() => switchDiagram('dep_graph')}
                  disabled={busy}
                >
                  Dependency Graph
                </button>
              </div>
            </div>

            {/* Visualizer Legend */}
            <div className="graph-legend">
              <div className="legend-item">
                <span className="legend-swatch class" />
                <span>Class</span>
              </div>
              <div className="legend-item">
                <span className="legend-swatch function" />
                <span>Function</span>
              </div>
              <div className="legend-item">
                <span className="legend-swatch method" />
                <span>Method</span>
              </div>
              <div className="legend-item">
                <span className="legend-swatch test" />
                <span>Test File (🧪)</span>
              </div>
              <div className="legend-hint">
                💡 Click any node to illuminate its blast radius
              </div>
            </div>

            {/* 3. Blast Radius Interaction Banner */}
            {impact && (
              <div className="blast-banner">
                <div className="blast-banner-header">
                  <div className="blast-target-info">
                    <span className="blast-pulse-dot" />
                    <div>
                      <div className="blast-target-name">
                        Target: <span className="blast-target-fqn">{impact.changed_fqn}</span>
                      </div>
                    </div>
                  </div>
                  <button
                    className="btn-back-graph"
                    onClick={handleClearFocus}
                    disabled={busy}
                    title="Clear highlighting and restore full graph view"
                  >
                    ← Back to Full Graph
                  </button>
                </div>

                <div className="blast-stats-row">
                  <span className="blast-chip target">
                    Target Symbol
                  </span>
                  <span className="blast-chip direct">
                    ● Direct Callers: <strong>{impact.direct_callers.length}</strong>
                  </span>
                  <span className="blast-chip transitive">
                    ● Transitive Callers: <strong>{impact.transitive_callers.length}</strong>
                  </span>
                  <span className="blast-chip tests">
                    🧪 Affected Tests: <strong>{impact.affected_tests.length}</strong>
                  </span>
                  <span className="blast-chip files">
                    📄 Affected Files: <strong>{impact.affected_files.length}</strong>
                  </span>
                </div>
              </div>
            )}

            {/* Rendered Graph SVG Canvas */}
            {diagram ? (
              <Diagram
                code={diagram}
                onNodeClick={handleNodeClick}
                impact={impact}
                containerRef={diagramRef}
              />
            ) : (
              <div className="diagram-empty">
                <span>⚙️</span>
                <span>Select a repository and click Analyze to generate the call graph</span>
              </div>
            )}
          </section>

          {/* ── Right Column: 4. Q&A Assistant Chat Panel ── */}
          <section className="panel panel-chat">
            <div className="panel-header">
              <span className="panel-title">
                <span>💬</span> Onboarding Assistant & Q&A
              </span>
              {chat.length > 0 && (
                <button
                  className="pill"
                  onClick={() => setChat([])}
                  title="Clear conversation"
                >
                  Clear Chat
                </button>
              )}
            </div>

            <div className="chat-messages">
              {chat.length === 0 ? (
                <div className="chat-empty">
                  <p>Ask anything about this repository's codebase, data flow, or architecture.</p>
                  <div className="chat-suggested">
                    <button
                      className="suggested-btn"
                      onClick={() => handleSuggestedQuestion('What does UserService do and how is it used?')}
                    >
                      "What does UserService do?"
                    </button>
                    <button
                      className="suggested-btn"
                      onClick={() => handleSuggestedQuestion('What is the blast radius if get_user signature changes?')}
                    >
                      "What calls get_user?"
                    </button>
                    <button
                      className="suggested-btn"
                      onClick={() => handleSuggestedQuestion('Where are the unit tests located and what do they verify?')}
                    >
                      "Where are tests located?"
                    </button>
                  </div>
                </div>
              ) : (
                chat.map((m, i) => (
                  <div key={i} className={`bubble bubble-${m.role}`}>
                    <div className="bubble-role-label">
                      {m.role === 'user' ? 'You' : 'RepoPilot Assistant'}
                    </div>

                    {m.role === 'user' ? (
                      <p className="bubble-text">{m.text}</p>
                    ) : (
                      <div
                        className="bubble-text md-body"
                        dangerouslySetInnerHTML={{ __html: renderMarkdown(m.text) }}
                      />
                    )}

                    {/* Citations & Confidence Chip (Requirement 4) */}
                    {m.role === 'assistant' && (
                      <div className="citations">
                        {(m.citations || []).slice(0, 4).map((c, j) => {
                          const fileName = c.file_path ? c.file_path.split('/').pop() : ''
                          return (
                            <span
                              key={j}
                              className="citation-chip"
                              title={c.fqn || c.file_path}
                            >
                              📍 <code>{fileName ? `${fileName}:${c.line}` : c.fqn}</code>
                            </span>
                          )
                        })}

                        {m.confidence !== undefined && (
                          <span
                            className={`confidence-chip ${
                              m.confidence >= 0.7 ? 'high' : m.confidence >= 0.4 ? 'medium' : 'low'
                            }`}
                            title="Retrieval-augmented confidence score"
                          >
                            {Math.round((m.confidence || 0) * 100)}% confidence
                          </span>
                        )}
                      </div>
                    )}
                  </div>
                ))
              )}
              <div ref={chatEndRef} />
            </div>

            {/* Chat Input Box */}
            <form className="chat-form" onSubmit={handleChat}>
              <input
                className="chat-input"
                value={question}
                onChange={e => setQuestion(e.target.value)}
                placeholder="Ask a question about the codebase..."
                disabled={busy}
              />
              <button
                type="submit"
                className="btn btn-primary"
                disabled={busy || !question.trim()}
              >
                Send
              </button>
            </form>
          </section>
        </div>
      )}

      {/* ── Collapsible ONBOARDING.md Markdown Preview ── */}
      {onboarding && (
        <details className="onboarding-preview">
          <summary>
            <span>📄 Exported ONBOARDING.md Preview</span>
            <span style={{ fontSize: '11px', color: '#818cf8' }}>Click to toggle</span>
          </summary>
          <pre>{onboarding}</pre>
        </details>
      )}
    </div>
  )
}
