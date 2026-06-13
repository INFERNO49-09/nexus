import React, { useEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import {
  Bot, Brain, Check, ChevronRight, Cpu, Database, Download, FlaskConical,
  Menu, MessageSquare, RefreshCw, Search, Send, Settings, Sparkles, Square,
  Wrench, X,
} from 'lucide-react';
import './styles.css';

const pages = [
  { id: 'chat', label: 'Chat', group: 'Core', icon: MessageSquare },
  { id: 'agents', label: 'Agents', group: 'Core', icon: Bot },
  { id: 'research', label: 'Research', group: 'Core', icon: FlaskConical },
  { id: 'memory', label: 'Memory', group: 'Intelligence', icon: Brain },
  { id: 'skills', label: 'Skills', group: 'Intelligence', icon: Wrench },
  { id: 'models', label: 'Models', group: 'Intelligence', icon: Cpu },
  { id: 'settings', label: 'Settings', group: 'Developer', icon: Settings },
];

function escapeHtml(text) {
  return String(text ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function markdown(text) {
  return escapeHtml(text)
    .replace(/```(\w*)\n?([\s\S]*?)```/g, '<pre>$2</pre>')
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.*?)\*/g, '<em>$1</em>')
    .replace(/^### (.+)$/gm, '<h3>$1</h3>')
    .replace(/^## (.+)$/gm, '<h2>$1</h2>')
    .replace(/^# (.+)$/gm, '<h1>$1</h1>')
    .replace(/\n/g, '<br>');
}

function Thinking() {
  return <span className="thinking"><span /><span /><span /></span>;
}

function App() {
  const [apiBase, setApiBase] = useState(localStorage.getItem('nexus_api') || window.location.origin);
  const [page, setPage] = useState('chat');
  const [collapsed, setCollapsed] = useState(false);
  const [toast, setToast] = useState(null);
  const [status, setStatus] = useState(null);
  const [hardware, setHardware] = useState(null);
  const [models, setModels] = useState({ catalog: [], installed: [] });
  const [activeModel, setActiveModel] = useState('');
  const [memoryStats, setMemoryStats] = useState(null);
  const apiRef = useRef(apiBase);

  useEffect(() => {
    apiRef.current = apiBase;
    localStorage.setItem('nexus_api', apiBase);
  }, [apiBase]);

  const notify = (message, type = '') => {
    setToast({ message, type });
    setTimeout(() => setToast(null), 3300);
  };

  const requestJson = async (path, opts = {}) => {
    const res = await fetch(apiRef.current + path, {
      headers: { 'Content-Type': 'application/json', ...(opts.headers || {}) },
      ...opts,
    });
    if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`);
    return res.json();
  };

  const refreshStatus = async () => {
    try {
      const [s, hw, m, ms] = await Promise.all([
        requestJson('/api/system/status'),
        requestJson('/api/system/hardware'),
        requestJson('/api/models'),
        requestJson('/api/memory/stats').catch(() => null),
      ]);
      setStatus(s);
      setHardware(hw);
      setModels(m);
      setMemoryStats(ms);
      if (!activeModel && m.installed?.length) setActiveModel(m.installed[0].name);
    } catch {
      setStatus(null);
    }
  };

  useEffect(() => {
    refreshStatus();
    const id = setInterval(refreshStatus, 30000);
    return () => clearInterval(id);
  }, []);

  const activePage = pages.find((p) => p.id === page);

  return (
    <div className="app">
      <aside className={`sidebar ${collapsed ? 'collapsed' : ''}`}>
        <div className="logo"><div className="logo-mark">NX</div><span className="logo-text">Nexus</span></div>
        <nav className="nav">
          {['Core', 'Intelligence', 'Developer'].map((group) => (
            <React.Fragment key={group}>
              <div className="nav-label">{group}</div>
              {pages.filter((p) => p.group === group).map((item) => {
                const Icon = item.icon;
                return (
                  <button key={item.id} className={`nav-item ${page === item.id ? 'active' : ''}`} onClick={() => setPage(item.id)}>
                    <Icon className="nav-icon" size={18} />
                    <span className="nav-text">{item.label}</span>
                    {item.id === 'memory' && <span className="nav-badge">{memoryStats?.count || ''}</span>}
                  </button>
                );
              })}
            </React.Fragment>
          ))}
        </nav>
        <div className="status-bar">
          <div className="status-item"><span className={`status-dot ${status?.ollama?.available ? 'green' : ''}`} /><span className="status-text">{status?.ollama?.available ? `Ollama ${status.ollama.models_installed} models` : 'Backend offline'}</span></div>
          <div className="status-item"><span className={`status-dot ${status?.ollama?.running?.length ? 'green' : 'amber'}`} /><span className="status-text">{status?.ollama?.running?.[0]?.name || 'No model loaded'}</span></div>
        </div>
      </aside>

      <main className="main">
        <div className="topbar">
          <button className="icon-btn" onClick={() => setCollapsed(!collapsed)} title="Toggle sidebar"><Menu size={18} /></button>
          <span className="topbar-title">{activePage?.label}</span>
          <span className="topbar-sub">{status ? `v${status.version}` : 'Disconnected'}</span>
          <div className="spacer" />
          <select value={activeModel} onChange={(e) => setActiveModel(e.target.value)} className="model-select">
            <option value="">Select model</option>
            {models.installed?.map((m) => <option key={m.name} value={m.name}>{m.name}</option>)}
          </select>
          <button className="pill-btn" onClick={refreshStatus}><RefreshCw size={14} /> Refresh</button>
        </div>

        <div className="content">
          {page === 'chat' && <Chat api={requestJson} apiBase={apiBase} model={activeModel} notify={notify} />}
          {page === 'models' && <Models data={models} apiBase={apiBase} setActiveModel={setActiveModel} refresh={refreshStatus} notify={notify} />}
          {page === 'agents' && <Agents apiBase={apiBase} model={activeModel} notify={notify} />}
          {page === 'research' && <Research apiBase={apiBase} model={activeModel} notify={notify} />}
          {page === 'memory' && <Memory api={requestJson} stats={memoryStats} refreshStatus={refreshStatus} />}
          {page === 'skills' && <Skills api={requestJson} notify={notify} />}
          {page === 'settings' && <SettingsPage apiBase={apiBase} setApiBase={setApiBase} status={status} hardware={hardware} refresh={refreshStatus} />}
        </div>
      </main>
      {toast && <div className={`toast ${toast.type}`}>{toast.message}</div>}
    </div>
  );
}

function Chat({ api, apiBase, model, notify }) {
  const [messages, setMessages] = useState([{ role: 'ai', content: "Hello! I'm <strong>Nexus</strong>, your local AI assistant.<br><br>Select a model and start chatting.", meta: 'Ready', html: true }]);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const [convId, setConvId] = useState(null);
  const [useWeb, setUseWeb] = useState(true);
  const [useMemory, setUseMemory] = useState(true);
  const [stream, setStream] = useState(true);
  const bottom = useRef(null);

  useEffect(() => bottom.current?.scrollIntoView({ behavior: 'smooth' }), [messages]);

  const send = async () => {
    const msg = input.trim();
    if (!msg || busy) return;
    if (!model) return notify('Please select a model first', 'error');
    setInput('');
    setBusy(true);
    const aiIndex = messages.length + 1;
    setMessages((m) => [...m, { role: 'user', content: msg }, { role: 'ai', loading: true, content: '', meta: '' }]);
    try {
      if (!stream) {
        const result = await api('/api/chat', { method: 'POST', body: JSON.stringify({ message: msg, model, use_web_search: useWeb, use_memory: useMemory, conversation_id: convId, stream: false }) });
        setConvId(result.conversation_id);
        setMessages((m) => m.map((x, i) => i === aiIndex ? { role: 'ai', content: result.content, meta: `${model} ${result.tokens} tokens ${result.tps} tok/s ${result.elapsed_s}s` } : x));
      } else {
        const res = await fetch(`${apiBase}/api/chat/stream`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ message: msg, model, use_web_search: useWeb, use_memory: useMemory, conversation_id: convId, stream: true }) });
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let full = '';
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          for (const line of decoder.decode(value).split('\n')) {
            if (!line.startsWith('data:')) continue;
            const raw = line.slice(5).trim();
            if (raw === '[DONE]') break;
            const ev = JSON.parse(raw);
            if (ev.type === 'token') {
              full += ev.content;
              setMessages((m) => m.map((x, i) => i === aiIndex ? { ...x, loading: false, content: full } : x));
            }
            if (ev.type === 'searching') setMessages((m) => m.map((x, i) => i === aiIndex ? { ...x, meta: 'Searching the web' } : x));
            if (ev.type === 'done') {
              setConvId(ev.conversation_id);
              setMessages((m) => m.map((x, i) => i === aiIndex ? { ...x, meta: `${model} ${ev.tokens} tokens ${ev.tps} tok/s ${ev.elapsed_s}s` } : x));
            }
            if (ev.type === 'error') throw new Error(ev.message);
          }
        }
      }
    } catch (e) {
      setMessages((m) => m.map((x, i) => i === aiIndex ? { role: 'ai', content: `Error: ${e.message}`, meta: 'Failed' } : x));
    } finally {
      setBusy(false);
    }
  };

  return <div className="chat-layout">
    <div className="chat-area">
      <div className="messages">
        {messages.map((m, i) => <div key={i} className={`msg ${m.role === 'user' ? 'user' : ''}`}>
          <div className={`msg-avatar ${m.role === 'user' ? 'user' : 'ai'}`}>{m.role === 'user' ? 'U' : 'NX'}</div>
          <div><div className={`msg-bubble ${m.role === 'user' ? 'user' : 'ai'}`}>{m.loading ? <Thinking /> : <span dangerouslySetInnerHTML={{ __html: m.html ? m.content : markdown(m.content) }} />}</div><div className="msg-meta">{m.meta}</div></div>
        </div>)}
        <div ref={bottom} />
      </div>
      <div className="chat-input-area">
        <div className="tool-bar">
          <button className={`tool-chip ${useWeb ? 'on' : ''}`} onClick={() => setUseWeb(!useWeb)}>Web search</button>
          <button className={`tool-chip ${useMemory ? 'on' : ''}`} onClick={() => setUseMemory(!useMemory)}>Memory</button>
          <button className={`tool-chip ${stream ? 'on' : ''}`} onClick={() => setStream(!stream)}>Stream</button>
        </div>
        <div className="input-box">
          <textarea value={input} onChange={(e) => setInput(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } }} className="chat-textarea" placeholder="Message Nexus" rows="1" />
          <button className="send-btn" disabled={busy} onClick={send}><Send size={16} /></button>
        </div>
      </div>
    </div>
    <div className="side-panel">
      <Panel title="Active Model">{model || 'No model selected'}</Panel>
      <Panel title="Context">{Math.floor(messages.length / 2)} messages in history</Panel>
      <Panel title="Mode">{stream ? 'Streaming responses' : 'Blocking responses'}</Panel>
    </div>
  </div>;
}

function Panel({ title, children }) {
  return <div className="panel-section"><div className="panel-title">{title}</div><div className="muted">{children}</div></div>;
}

function Models({ data, apiBase, setActiveModel, refresh, notify }) {
  const [filter, setFilter] = useState('');
  const [query, setQuery] = useState('');
  const [pulling, setPulling] = useState(null);
  const [progress, setProgress] = useState(0);
  const items = useMemo(() => (data.catalog || []).filter((m) => (filter === 'installed' ? m.installed : !filter || m.category === filter) && (`${m.display} ${m.desc}`).toLowerCase().includes(query.toLowerCase())), [data, filter, query]);
  const pull = async (name) => {
    setPulling(name);
    try {
      const res = await fetch(`${apiBase}/api/models/pull`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ model_name: name }) });
      const reader = res.body.getReader();
      const dec = new TextDecoder();
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        for (const line of dec.decode(value).split('\n')) {
          if (!line.startsWith('data:')) continue;
          const ev = JSON.parse(line.slice(5));
          if (ev.completed && ev.total) setProgress(Math.round((ev.completed / ev.total) * 100));
          if (ev.status === 'success') notify(`${name} downloaded`, 'success');
        }
      }
      refresh();
    } catch (e) { notify(`Download failed: ${e.message}`, 'error'); }
    setPulling(null);
    setProgress(0);
  };
  return <div className="models-page">
    <div className="page-head"><h1>Model Catalog</h1><div className="search-box"><Search size={15} /><input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search models" /></div></div>
    <div className="filters">{['', 'chat', 'code', 'reasoning', 'vision', 'installed'].map((f) => <button key={f} className={`filter-chip ${filter === f ? 'on' : ''}`} onClick={() => setFilter(f)}>{f || 'All'}</button>)}</div>
    <div className="models-grid">{items.map((m) => <div key={m.name} className={`model-tile ${m.installed ? 'installed' : ''}`}>
      <div className="tile-top"><div><div className="tile-name">{m.display}</div><div className="tile-provider">{m.provider}</div></div>{m.installed && <span className="installed-badge">INSTALLED</span>}</div>
      <div className="tags">{(m.tags || []).map((t) => <span className={`tag ${t}`} key={t}>{t}</span>)}</div>
      <div className="tile-desc">{m.desc}</div>
      <div className="tile-stats"><div><span>{m.params}</span>params</div><div><span>{m.ctx}</span>context</div><div><span>{m.size_gb}GB</span>size</div></div>
      {m.installed ? <button className="serve-btn" onClick={() => setActiveModel(m.name)}><ChevronRight size={14} /> Use this model</button> : <><button className="pull-btn" disabled={pulling === m.name} onClick={() => pull(m.name)}><Download size={14} /> {pulling === m.name ? `Downloading ${progress}%` : `Download (${m.size_gb}GB)`}</button>{pulling === m.name && <div className="progress-bar"><div style={{ width: `${progress}%` }} /></div>}</>}
    </div>)}</div>
  </div>;
}

function Agents({ apiBase, model, notify }) {
  const [task, setTask] = useState('');
  const [steps, setSteps] = useState([]);
  const [answer, setAnswer] = useState('');
  const [running, setRunning] = useState(false);
  const run = async () => {
    if (!task.trim()) return;
    if (!model) return notify('Select a model first', 'error');
    setSteps([]); setAnswer(''); setRunning(true);
    try {
      const res = await fetch(`${apiBase}/api/agents/run`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ task, model }) });
      const reader = res.body.getReader(); const dec = new TextDecoder();
      while (true) {
        const { done, value } = await reader.read(); if (done) break;
        for (const line of dec.decode(value).split('\n')) {
          if (!line.startsWith('data:')) continue;
          const raw = line.slice(5).trim(); if (raw === '[DONE]') break;
          const ev = JSON.parse(raw);
          if (ev.event === 'step') setSteps((s) => [...s, ev.step]);
          if (ev.event === 'done') setAnswer(ev.answer || '');
        }
      }
    } catch (e) { notify(e.message, 'error'); }
    setRunning(false);
  };
  return <div className="agents-layout"><div className="agent-list"><h2>Run an Agent</h2><textarea value={task} onChange={(e) => setTask(e.target.value)} placeholder="Describe the task for the agent" /><button className="primary-btn" onClick={run} disabled={running}><Bot size={15} /> Run Agent</button></div><div className="agent-workspace">{!steps.length && !answer ? <Empty text="Enter a task and run an agent." /> : <div className="step-trace">{steps.map((s, i) => <div className="step" key={i}><div className="step-num done">{s.is_final ? <Check size={13} /> : s.step}</div><div className="step-content"><b>{s.action || 'thought'}</b><p>{s.thought}</p>{s.observation && <pre>{s.observation}</pre>}</div></div>)}{answer && <div className="report-content" dangerouslySetInnerHTML={{ __html: markdown(answer) }} />}</div>}</div></div>;
}

function Research({ apiBase, model, notify }) {
  const [question, setQuestion] = useState('');
  const [depth, setDepth] = useState(15);
  const [events, setEvents] = useState([]);
  const [report, setReport] = useState(null);
  const run = async () => {
    if (!question.trim()) return notify('Enter a research question', 'error');
    if (!model) return notify('Select a model first', 'error');
    setEvents([]); setReport(null);
    try {
      const res = await fetch(`${apiBase}/api/research/run`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ question, depth, model }) });
      const reader = res.body.getReader(); const dec = new TextDecoder();
      while (true) {
        const { done, value } = await reader.read(); if (done) break;
        for (const line of dec.decode(value).split('\n')) {
          if (!line.startsWith('data:')) continue;
          const raw = line.slice(5).trim(); if (raw === '[DONE]') break;
          const ev = JSON.parse(raw);
          if (ev.event === 'progress') setEvents((x) => [...x, ev]);
          if (ev.event === 'done') setReport(ev);
        }
      }
    } catch (e) { notify(e.message, 'error'); }
  };
  return <div className="research-layout"><h1>Deep Research</h1><div className="research-box"><textarea value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="What would you like researched?" /><div className="filters">{[5, 15, 40].map((n) => <button key={n} className={`depth-btn ${depth === n ? 'on' : ''}`} onClick={() => setDepth(n)}>{n === 5 ? 'Quick' : n === 15 ? 'Standard' : 'Deep'} {n}</button>)}<button className="primary-btn push" onClick={run}><Sparkles size={15} /> Research</button></div></div>{events.map((e, i) => <div className="progress-step" key={i}>{e.message}</div>)}{report && <div className="report-content"><h2>{question}</h2><div dangerouslySetInnerHTML={{ __html: markdown(report.report || '') }} /><h3>Sources</h3><div className="source-grid">{(report.sources || []).map((s, i) => <div className="source-card" key={i}><b>[{i + 1}] {s.title}</b><span>{s.url}</span></div>)}</div></div>}</div>;
}

function Memory({ api, stats, refreshStatus }) {
  const [entries, setEntries] = useState([]);
  const [query, setQuery] = useState('');
  const load = async () => { const data = await api('/api/memory?limit=100'); setEntries(data.entries || []); refreshStatus(); };
  useEffect(() => { load().catch(() => {}); }, []);
  const search = async (value) => {
    setQuery(value);
    if (!value.trim()) return load();
    const data = await api('/api/memory/search', { method: 'POST', body: JSON.stringify({ query: value, n: 20 }) });
    setEntries(data.results || []);
  };
  return <div className="memory-layout"><h1>Persistent Memory</h1><div className="mem-stats">{['Total', 'Facts', 'Preferences', 'Context'].map((label, i) => <div className="mem-stat" key={label}><div className="mem-stat-val">{i === 0 ? stats?.count || 0 : stats?.by_type?.[['fact', 'pref', 'ctx'][i - 1]] || 0}</div><span>{label}</span></div>)}</div><div className="row"><div className="search-box"><Search size={15} /><input value={query} onChange={(e) => search(e.target.value)} placeholder="Search memories" /></div><button className="pill-btn" onClick={load}><RefreshCw size={14} /> Refresh</button></div><div className="mem-entries">{entries.map((m) => <div className="mem-entry" key={m.id || m.text}><span className={`mem-badge ${m.type}`}>{m.type}</span><div><p>{m.text}</p><small>{m.timestamp?.slice(0, 16)} {m.source}</small></div></div>)}</div></div>;
}

function Skills({ api, notify }) {
  const [skills, setSkills] = useState([]);
  useEffect(() => { api('/api/skills').then((d) => setSkills(d.skills || [])).catch(() => {}); }, []);
  const refine = async (name) => { try { await api(`/api/skills/${name}/refine`, { method: 'POST' }); notify(`${name} refined`, 'success'); } catch (e) { notify(e.message, 'error'); } };
  return <div className="skills-layout"><h1>Skill Library</h1><div className="skills-grid">{skills.map((s) => <div className="skill-card" key={s.name}><div className="skill-icon">{s.icon || <Wrench size={20} />}</div><h2>{s.name}</h2><small>{s.version}</small><p>{s.description || s.desc}</p><div className="perf-bar"><div style={{ width: `${s.perf || 0}%` }} /></div>{!s.builtin && <button className="pill-btn" onClick={() => refine(s.name)}>AI Refine</button>}</div>)}</div></div>;
}

function SettingsPage({ apiBase, setApiBase, status, hardware, refresh }) {
  return <div className="settings-layout"><h1>Settings</h1><div className="setting-group"><h2>Connection</h2><div className="setting-row"><div><b>API Base URL</b><span>Nexus backend address</span></div><input className="input-field" value={apiBase} onChange={(e) => setApiBase(e.target.value)} /></div><div className="setting-row"><div><b>Ollama URL</b><span>{status?.ollama?.url || 'Unknown'}</span></div><button className="pill-btn" onClick={refresh}><RefreshCw size={14} /> Check</button></div></div><div className="setting-group"><h2>System Status</h2><div className="status-grid"><span>Ollama <b>{status?.ollama?.available ? 'Online' : 'Offline'}</b></span><span>Models <b>{status?.ollama?.models_installed || 0}</b></span><span>Memory <b>{status?.memory?.count || 0}</b></span><span>GPU <b>{hardware?.gpu?.[0]?.name || 'Not detected'}</b></span></div></div><div className="setting-group"><h2>OpenAI-Compatible API</h2><pre>{`from openai import OpenAI\nclient = OpenAI(base_url="http://localhost:11434/v1", api_key="nexus")`}</pre></div></div>;
}

function Empty({ text }) {
  return <div className="empty"><Square size={18} /> {text}</div>;
}

createRoot(document.getElementById('root')).render(<App />);
