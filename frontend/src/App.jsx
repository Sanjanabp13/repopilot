import PropTypes from 'prop-types'
import { useEffect, useMemo, useRef, useState } from 'react'
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  Handle,
  Position,
} from 'reactflow'
import 'reactflow/dist/style.css'

const API = 'http://localhost:8000'
const PRIVACY_KEY = 'repopilot-privacy-consent'

async function post(path, body, timeoutMs = 180000) {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  try {
    const response = await fetch(`${API}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: controller.signal,
    })
    if (!response.ok) {
      const errorBody = await response.json().catch(() => ({ detail: response.statusText }))
      throw new Error(errorBody.detail || response.statusText)
    }
    return response.json()
  } catch (error) {
    if (error?.name === 'AbortError') {
      throw new Error('The backend timed out while cloning or analyzing a large repository. Please retry with a smaller repo or a slower network connection.')
    }
    throw error
  } finally {
    clearTimeout(timer)
  }
}

async function get(path) {
  const response = await fetch(`${API}${path}`)
  if (!response.ok) throw new Error(response.statusText)
  return response.json()
}

function normalizePath(filePath) {
  return filePath ? filePath.split(/[\\/]/).pop() : ''
}

function renderMarkdown(text) {
  if (!text) return ''
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/```([\w-]*)\n([\s\S]*?)```/g, '<pre class="code-block"><code>$2</code></pre>')
    .replace(/`([^`]+)`/g, '<code class="inline-code">$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/^### (.+)$/gm, '<h4 class="md-h4">$1</h4>')
    .replace(/^## (.+)$/gm, '<h3 class="md-h3">$1</h3>')
    .replace(/^- (.+)$/gm, '<li>$1</li>')
    .replace(/(<li>[\s\S]*?<\/li>(?:\n<li>[\s\S]*?<\/li>)*)/g, '<ul>$1</ul>')
    .replace(/\n{2,}/g, '</p><p>')
    .replace(/\n/g, '<br/>')
}

function getNodeAccent(kind = 'module') {
  const palette = {
    module: '#60a5fa',
    class: '#c084fc',
    function: '#34d399',
    method: '#fbbf24',
    test: '#f87171',
  }
  return palette[kind] || '#94a3b8'
}

function RepositoryNode({ data }) {
  const accent = data.accent || '#60a5fa'

  return (
    <div className="repo-node" style={{ '--accent': accent }}>
      <Handle type="target" position={Position.Left} className="node-handle" />
      <div className="node-header">
        <span className="node-kind">{data.kind || 'module'}</span>
      </div>
      <div className="node-title">{data.label}</div>
      <div className="node-meta">{data.filePath ? normalizePath(data.filePath) : 'internal'}</div>
      {data.line ? <div className="node-line">L{data.line}</div> : null}
      <Handle type="source" position={Position.Right} className="node-handle" />
    </div>
  )
}

RepositoryNode.propTypes = {
  data: PropTypes.shape({
    accent: PropTypes.string,
    kind: PropTypes.string,
    label: PropTypes.string,
    filePath: PropTypes.string,
    line: PropTypes.number,
  }).isRequired,
}

const nodeTypes = { repository: RepositoryNode }

function buildFlowNodes(graph, impact) {
  if (!graph || !Array.isArray(graph.nodes)) return []

  const targetFqn = impact?.changed_fqn || ''
  const directSet = new Set((impact?.direct_callers || []).map((symbol) => symbol.fqn))
  const transitiveSet = new Set((impact?.transitive_callers || []).map((symbol) => symbol.fqn))
  const testSet = new Set((impact?.affected_tests || []).map((symbol) => symbol.fqn))

  return graph.nodes.map((node, index) => {
    const kind = (node.kind || 'module').toLowerCase()
    const accent = getNodeAccent(kind === 'test' ? 'test' : kind)
    const isTarget = targetFqn && node.id === targetFqn
    const isDirect = directSet.has(node.id)
    const isTransitive = transitiveSet.has(node.id)
    const isTest = testSet.has(node.id)

    let border = '#334155'
    let opacity = 1
    if (impact) {
      if (isTarget) border = '#ef4444'
      else if (isDirect) border = '#f59e0b'
      else if (isTransitive) border = '#facc15'
      else if (isTest) border = '#60a5fa'
      else opacity = 0.25
    }

    return {
      id: String(node.id),
      type: 'repository',
      position: {
        x: 120 + (index % 5) * 220,
        y: 50 + Math.floor(index / 5) * 150,
      },
      data: {
        label: node.label || node.id.split('.').pop(),
        kind,
        filePath: node.file_path || '',
        line: node.line || 0,
        accent: isTarget ? '#ef4444' : isDirect ? '#f59e0b' : isTransitive ? '#facc15' : isTest ? '#60a5fa' : accent,
      },
      style: {
        background: '#0f172a',
        borderRadius: 14,
        border: `1px solid ${border}`,
        opacity,
        boxShadow: isTarget ? '0 0 0 2px rgba(239,68,68,0.45)' : 'none',
      },
    }
  })
}

function buildFlowEdges(graph, impact) {
  if (!graph || !Array.isArray(graph.edges)) return []

  const target = impact?.changed_fqn || ''
  const directSet = new Set((impact?.direct_callers || []).map((symbol) => symbol.fqn))
  const transitiveSet = new Set((impact?.transitive_callers || []).map((symbol) => symbol.fqn))
  const testSet = new Set((impact?.affected_tests || []).map((symbol) => symbol.fqn))

  return graph.edges.map((edge) => {
    const sourceInScope = target === edge.source || directSet.has(edge.source) || transitiveSet.has(edge.source) || testSet.has(edge.source)
    const targetInScope = target === edge.target || directSet.has(edge.target) || transitiveSet.has(edge.target) || testSet.has(edge.target)
    const visible = !impact || sourceInScope || targetInScope

    return {
      id: String(edge.id),
      source: String(edge.source),
      target: String(edge.target),
      label: edge.label || '',
      type: 'smoothstep',
      animated: false,
      markerEnd: { type: 'arrowclosed', color: visible ? '#94a3b8' : '#334155' },
      style: {
        stroke: visible ? '#94a3b8' : '#334155',
        strokeWidth: visible ? 1.6 : 1,
        opacity: impact ? (visible ? 1 : 0.2) : 0.8,
      },
    }
  })
}

export default function App() {
  const [source, setSource] = useState('tests/fixtures/sample_project')
  const [session, setSession] = useState(null)
  const [stats, setStats] = useState(null)
  const [graphKind, setGraphKind] = useState('call_graph')
  const [graph, setGraph] = useState({ nodes: [], edges: [] })
  const [impact, setImpact] = useState(null)
  const [chat, setChat] = useState([])
  const [chatPending, setChatPending] = useState(false)
  const [question, setQuestion] = useState('')
  const [status, setStatus] = useState('')
  const [statusOk, setStatusOk] = useState(true)
  const [busy, setBusy] = useState(false)
  const [onboarding, setOnboarding] = useState('')
  const [serverOk, setServerOk] = useState(null)
  const [showPrivacyModal, setShowPrivacyModal] = useState(() => {
    if (typeof window === 'undefined') return false
    return window.localStorage.getItem(PRIVACY_KEY) !== 'true'
  })

  const chatEndRef = useRef(null)

  useEffect(() => {
    const checkServer = () => {
      fetch(`${API}/health`)
        .then((response) => setServerOk(response.ok))
        .catch(() => setServerOk(false))
    }

    checkServer()
    const timer = setInterval(checkServer, 15000)
    return () => clearInterval(timer)
  }, [])

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [chat])

  const flowNodes = useMemo(() => buildFlowNodes(graph, impact), [graph, impact])
  const flowEdges = useMemo(() => buildFlowEdges(graph, impact), [graph, impact])

  function setMsg(msg, ok = true) {
    setStatus(msg)
    setStatusOk(ok)
  }

  function hasConsent() {
    if (typeof window === 'undefined') return false
    return window.localStorage.getItem(PRIVACY_KEY) === 'true'
  }

  function clearSessionData() {
    setSession(null)
    setStats(null)
    setGraph({ nodes: [], edges: [] })
    setImpact(null)
    setChat([])
    setQuestion('')
    setOnboarding('')
    setMsg('Repository map restored')
  }

  function handleConsent(granted) {
    if (granted) {
      if (typeof window !== 'undefined') window.localStorage.setItem(PRIVACY_KEY, 'true')
      setShowPrivacyModal(false)
      setStatus('Privacy consent recorded')
      setStatusOk(true)
      return
    }
    if (typeof window !== 'undefined') window.localStorage.removeItem(PRIVACY_KEY)
    clearSessionData()
    setShowPrivacyModal(false)
  }

  async function loadDiagram(sid, kind) {
    try {
      const response = await get(`/diagram?analysis_id=${sid}&kind=${kind}`)
      setGraph(response.graph || { nodes: [], edges: [] })
      setStatus('Repository map ready')
    } catch (error) {
      setMsg(`Diagram error: ${error.message}`, false)
    }
  }

  async function handleAnalyze() {
    if (!source.trim()) return
    if (!hasConsent()) {
      setShowPrivacyModal(true)
      return
    }

    setBusy(true)
    setMsg('Analyzing repository and building the repository map…')
    setImpact(null)

    try {
      const response = await post('/analyze', {
        source: source.trim(),
        languages: ['python'],
      }, 300000)
      setSession(response.analysis_id)
      setStats(response)
      setMsg(`Indexed ${response.total_symbols} symbols in ${response.modules} modules with ${response.parse_errors} parse errors`)
      await loadDiagram(response.analysis_id, graphKind)
    } catch (error) {
      setMsg(`Analysis error: ${error.message}`, false)
    } finally {
      setBusy(false)
    }
  }

  async function switchDiagram(kind) {
    if (!session) return
    setImpact(null)
    setGraphKind(kind)
    await loadDiagram(session, kind)
  }

  const handleNodeClick = async (label) => {
    if (!session) return
    setBusy(true)
    setMsg(`Computing blast radius for: ${label}…`)
    try {
      const response = await post('/impact', {
        analysis_id: session,
        symbol_fqn: label,
      })
      setImpact(response)
      const affectedTests = response.affected_tests?.length || 0
      setMsg(`Blast radius updated: ${response.total_impact} affected symbols (${response.direct_callers.length} direct, ${affectedTests} tests)`)
    } catch (error) {
      setMsg(`Impact error: ${error.message}`, false)
    } finally {
      setBusy(false)
    }
  }

  function handleClearFocus() {
    setImpact(null)
    setMsg('Repository map restored')
  }

  function handleSuggestedQuestion(promptText) {
    setQuestion(promptText)
  }

  async function handleChat(event) {
    if (event) event.preventDefault()
    if (!session || !question.trim() || chatPending) return

    const q = question.trim()
    setQuestion('')
    setChat((previous) => [...previous, { role: 'user', text: q }])
    setChat((previous) => [...previous, { role: 'assistant', text: 'Reading the relevant files…', pending: true }])
    setChatPending(true)

    try {
      const response = await post('/chat', {
        analysis_id: session,
        question: q,
      }, 18000)

      setChat((previous) => {
        const next = previous.filter((message) => !(message.pending && message.role === 'assistant' && message.text === 'Reading the relevant files…'))
        return [...next, {
          role: 'assistant',
          text: response.answer,
          citations: response.citations || [],
          confidence: response.confidence || 0,
        }]
      })
    } catch (error) {
      setChat((previous) => {
        const next = previous.filter((message) => !(message.pending && message.role === 'assistant' && message.text === 'Reading the relevant files…'))
        return [...next, {
          role: 'assistant',
          text: 'The repository assistant timed out. I’m showing the best local evidence available from the repository index.',
          citations: [],
          confidence: 0,
        }]
      })
      setMsg(`Chat request timed out: ${error.message}`, false)
    } finally {
      setChatPending(false)
    }
  }

  async function handleExport() {
    if (!session) return
    setBusy(true)
    try {
      const response = await post('/export-onboarding', { analysis_id: session })
      setOnboarding(response.markdown)
      const blob = new Blob([response.markdown], { type: 'text/markdown' })
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = 'ONBOARDING.md'
      link.click()
      URL.revokeObjectURL(url)
      setMsg('ONBOARDING.md generated and downloaded successfully')
    } catch (error) {
      setMsg(`Export error: ${error.message}`, false)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand-group">
          <div className="brand-mark">RP</div>
          <div>
            <div className="brand-name">RepoPilot</div>
            <div className="brand-sub">Repository Pilot</div>
          </div>
        </div>

        <div className="topbar-actions">
          <button className="ghost-btn" onClick={() => setShowPrivacyModal(true)}>
            {hasConsent() ? 'Privacy' : 'Review privacy'}
          </button>

          <div className="server-pill">
            <span className={`server-led ${serverOk === true ? 'online' : serverOk === false ? 'offline' : 'pending'}`} />
            {serverOk === true ? 'Backend ready' : serverOk === false ? 'Backend offline' : 'Checking backend'}
          </div>
        </div>
      </header>

      <section className="toolbar">
        <div className="input-wrap">
          <span className="input-icon">⌂</span>
          <input
            value={source}
            onChange={(event) => setSource(event.target.value)}
            placeholder="Enter a local repo path or GitHub URL"
            onKeyDown={(event) => event.key === 'Enter' && handleAnalyze()}
            disabled={busy}
          />
        </div>

        <button className="primary-btn" onClick={handleAnalyze} disabled={busy || !source.trim()}>
          {busy ? 'Analyzing…' : 'Analyze repository'}
        </button>

        {session && (
          <button className="secondary-btn" onClick={handleExport} disabled={busy}>
            Export ONBOARDING.md
          </button>
        )}
      </section>

      <div className="preset-row">
        <button type="button" className="chip-btn" onClick={() => setSource('tests/fixtures/sample_project')}>tests/fixtures/sample_project</button>
        <button type="button" className="chip-btn" onClick={() => setSource('.')}>. (repo root)</button>
      </div>

      {status && <div className={`status-banner ${statusOk ? 'success' : 'error'}`}>{status}</div>}

      {stats && (
        <section className="stats-grid">
          <div className="stat-card"><span>Modules</span><strong>{stats.modules}</strong></div>
          <div className="stat-card"><span>Classes</span><strong>{stats.classes}</strong></div>
          <div className="stat-card"><span>Methods</span><strong>{stats.methods}</strong></div>
          <div className="stat-card"><span>Functions</span><strong>{stats.functions}</strong></div>
          <div className="stat-card"><span>Indexed chunks</span><strong>{stats.indexed_chunks}</strong></div>
        </section>
      )}

      {session && (
        <main className="layout-grid">
          <section className="panel">
            <div className="panel-header">
              <h2>Repository map</h2>
              <div className="segmented-control">
                <button className={graphKind === 'call_graph' ? 'active' : ''} onClick={() => switchDiagram('call_graph')} disabled={busy}>Call graph</button>
                <button className={graphKind === 'dep_graph' ? 'active' : ''} onClick={() => switchDiagram('dep_graph')} disabled={busy}>Dependency graph</button>
              </div>
            </div>

            <div className="legend-row">
              <span><i className="legend-dot module" /> Module</span>
              <span><i className="legend-dot class" /> Class</span>
              <span><i className="legend-dot function" /> Function</span>
              <span><i className="legend-dot method" /> Method</span>
              <span><i className="legend-dot test" /> Test</span>
            </div>

            {impact && (
              <div className="impact-banner">
                <div>
                  <div className="impact-label">Selected symbol</div>
                  <div className="impact-fqn">{impact.changed_fqn}</div>
                </div>
                <button className="impact-reset" onClick={handleClearFocus}>Back to Full Graph</button>
              </div>
            )}

            <div className="graph-wrap">
              {graph.nodes.length ? (
                <ReactFlow
                  nodes={flowNodes}
                  edges={flowEdges}
                  nodeTypes={nodeTypes}
                  fitView
                  minZoom={0.15}
                  maxZoom={1.8}
                  defaultViewport={{ x: 0, y: 0, zoom: 0.75 }}
                  onNodeClick={(_, node) => handleNodeClick(node.id)}
                  nodesDraggable
                  panOnDrag
                  className="repo-flow"
                >
                  <MiniMap pannable nodeColor={(node) => node.data.accent || '#4f46e5'} />
                  <Controls showInteractive={false} />
                  <Background color="#1f2937" gap={20} />
                </ReactFlow>
              ) : (
                <div className="empty-graph">Select a repository and click Analyze to generate the repository map.</div>
              )}
            </div>
          </section>

          <aside className="panel chat-panel">
            <div className="panel-header">
              <h2>Ask about this repository</h2>
              {chat.length > 0 && <button className="ghost-btn small" onClick={() => setChat([])}>Clear chat</button>}
            </div>

            <div className="chat-list">
              {chat.length === 0 ? (
                <div className="chat-empty">
                  <p>Ask about dependencies, call paths, or test impact.</p>
                  <div className="quick-actions">
                    <button type="button" onClick={() => handleSuggestedQuestion('What does get_user do and who calls it?')}>What does get_user do and who calls it?</button>
                    <button type="button" onClick={() => handleSuggestedQuestion('What is the blast radius if get_user changes?')}>What calls get_user?</button>
                    <button type="button" onClick={() => handleSuggestedQuestion('Where are the unit tests located and what do they verify?')}>Where are tests located?</button>
                  </div>
                </div>
              ) : (
                chat.map((message, index) => (
                  <div key={`${message.role}-${index}`} className={`chat-bubble ${message.role}`}>
                    <div className="chat-role">{message.role === 'user' ? 'You' : 'RepoPilot'}</div>
                    {message.pending ? (
                      <div className="pending-message">
                        <span>{message.text}</span>
                        <span className="loading-ring"><span /><span /><span /></span>
                      </div>
                    ) : (
                      <div className="message-body" dangerouslySetInnerHTML={{ __html: renderMarkdown(message.text) }} />
                    )}

                    {!message.pending && message.role === 'assistant' && (
                      <div className="citation-strip">
                        {(message.citations || []).slice(0, 4).map((citation, citationIndex) => (
                          <span key={`${citation.fqn || citationIndex}-${citationIndex}`} className="citation-pill">{normalizePath(citation.file_path)}:{citation.line}</span>
                        ))}
                        {message.confidence !== undefined && (
                          <span className={`confidence-badge ${message.confidence >= 0.7 ? 'high' : message.confidence >= 0.4 ? 'medium' : 'low'}`}>
                            {Math.round((message.confidence || 0) * 100)}%
                          </span>
                        )}
                      </div>
                    )}
                  </div>
                ))
              )}
              <div ref={chatEndRef} />
            </div>

            <form className="chat-form" onSubmit={handleChat}>
              <input
                value={question}
                onChange={(event) => setQuestion(event.target.value)}
                placeholder="Ask about the repository..."
                disabled={chatPending || busy}
              />
              <button type="submit" disabled={chatPending || busy || !question.trim()}>Send</button>
            </form>
          </aside>
        </main>
      )}

      {onboarding && (
        <details className="preview-panel">
          <summary>Exported ONBOARDING.md preview</summary>
          <pre>{onboarding}</pre>
        </details>
      )}

      {showPrivacyModal && (
        <div className="modal-backdrop" onClick={() => setShowPrivacyModal(false)}>
          <div className="modal-card" onClick={(event) => event.stopPropagation()}>
            <h3>Privacy and repository analysis</h3>
            <p>RepoPilot reads repository source code to build the map.</p>
            <p>The analysis is done in the local backend. Remote Git repositories are only used while the session is active.</p>
            <p>Gemini is optional. If enabled, repository context may be sent to Gemini for generation.</p>
            <p>You can revisit or revoke consent from the Privacy button in the header.</p>
            <div className="modal-actions">
              <button type="button" className="secondary-btn" onClick={() => handleConsent(false)}>Revoke</button>
              <button type="button" className="primary-btn" onClick={() => handleConsent(true)}>Accept</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
