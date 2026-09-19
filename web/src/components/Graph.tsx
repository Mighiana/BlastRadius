import { useId, useRef, useState } from 'react';
import { ArrowRight, Database, Globe2, KeyRound, Server, Shield, LockKeyhole } from 'lucide-react';
import type { Edge, Snapshot } from '../api';

function NodeIcon({ type }: { type: string }) {
  const Icon = type.includes('INTERNET') ? Globe2 : type.includes('SECURITY') ? Shield
    : type.includes('EC2') ? Server : type.includes('IAM') ? KeyRound
      : type.includes('SENSITIVE') ? LockKeyhole : Database;
  return <Icon size={22} aria-hidden="true" />;
}
function Evidence({ edge, index }: { edge: Edge; index: number }) {
  return <details className="evidence-item">
    <summary><span className="hop-number">{String(index + 1).padStart(2, '0')}</span><span>
      <strong>{edge.relationship}</strong><span className="resource">{edge.source} → {edge.target}</span>
    </span><span className="evidence-severity">{edge.severity}</span></summary>
    <div className="evidence-body"><p>{edge.reason}</p>
      <p className="muted">Source resource: <code>{edge.terraform_resource || 'Modeled relationship'}</code></p>
      {edge.confidence && <p className="muted">Confidence: {edge.confidence} · {edge.category}</p>}
      {edge.source_file && <p>Source file: <code>{edge.source_file}</code></p>}
      <pre><code>{edge.evidence || 'No additional source text supplied by the engine.'}</code></pre>
      {edge.remediation && <p>{edge.remediation}</p>}
    </div>
  </details>;
}
export function Graph({ snapshot, compact = false }: { snapshot: Snapshot; compact?: boolean }) {
  const [selected, setSelected] = useState('');
  const [selectedNode, setSelectedNode] = useState('');
  const [zoom, setZoom] = useState(1);
  const viewport = useRef<HTMLDivElement>(null);
  const labelId = useId();
  const path = snapshot.attack_paths.find(p => p.id === selected)
    ?? snapshot.attack_paths.find(p => p.reaches_sensitive) ?? snapshot.attack_paths[0];
  const nodes = path?.nodes.map(id => snapshot.graph.nodes.find(n => n.id === id)).filter(n => n !== undefined) ?? [];
  const inspected = snapshot.graph.nodes.find(node => node.id === selectedNode);
  return <div className="graph" data-testid="attack-graph">
    <div className="graph-toolbar"><span className="eyebrow">MODELED REACHABILITY</span>
      <span className="graph-legend"><i className={path?.reaches_sensitive ? 'dot red' : 'dot'} />{path?.reaches_sensitive ? 'Sensitive data reachable' : 'No critical path'}</span>
    </div>
    {snapshot.attack_paths.length > 1 && !compact && <label className="path-select">Explore an attack path
      <select value={path?.id} onChange={event => { setSelected(event.target.value); setSelectedNode(''); }}>
        {snapshot.attack_paths.map((item, i) => <option key={item.id} value={item.id}>Path {i + 1} · {item.severity} · {item.labels.at(-1)}</option>)}
      </select>
    </label>}
    {!compact && path && <div className="button-row graph-controls" aria-label="Graph viewport controls">
      <button className="button secondary" disabled={zoom >= 1.8} onClick={() => setZoom(value => Math.min(1.8, value + .2))}>Zoom in</button>
      <button className="button secondary" disabled={zoom <= 1} onClick={() => setZoom(value => Math.max(1, value - .2))}>Zoom out</button>
      <button className="button secondary" onClick={() => { setZoom(1); viewport.current?.scrollTo({ left: 0, top: 0 }); }}>Fit / reset</button>
      <button className="button secondary" disabled={zoom === 1} onClick={() => viewport.current?.scrollBy({ left: -200 })} aria-label="Pan graph left">Pan left</button>
      <button className="button secondary" disabled={zoom === 1} onClick={() => viewport.current?.scrollBy({ left: 200 })} aria-label="Pan graph right">Pan right</button>
      <span className="muted">{Math.round(zoom * 100)}%</span>
    </div>}
    {path ? <>
      <div className="graph-viewport" ref={viewport} tabIndex={compact ? undefined : 0} role={compact ? undefined : 'region'} aria-label={compact ? undefined : 'Selected attack path canvas'}>
      <ol style={{ width: `${zoom * 100}%` }} className={`graph-path ${path.reaches_sensitive ? 'critical' : ''}`} aria-label="Attack path">
        {nodes.map((node, index) => <li className="graph-step" key={node.id}>
          <div className={`graph-node ${node.sensitive ? 'sensitive' : ''} ${selectedNode === node.id ? 'selected-node' : ''}`}>
            <span className="node-icon"><NodeIcon type={node.type} /></span>
            <span className="node-type">{node.type.replaceAll('_', ' ')}</span>
            <strong>{node.name}</strong>
            {!compact && <code>{node.id}</code>}
            {!compact && <button className="node-select" aria-label={`Inspect node ${node.name}`} aria-pressed={selectedNode === node.id} onClick={() => setSelectedNode(node.id)}>Inspect node</button>}
          </div>
          {index < nodes.length - 1 && <span className="path-connector" aria-hidden="true"><ArrowRight size={18} /></span>}
        </li>)}
      </ol>
      </div>
      {!compact && <><p className="path-explanation">{path.explanation}</p>
        <h3 id={labelId} className="section-label">Per-hop evidence</h3>
        <div aria-labelledby={labelId}>{path.edges.map((edge, i) => <Evidence key={`${edge.source}-${edge.target}`} edge={edge} index={i} />)}</div>
      </>}
    </> : <div className="graph-clear">
      <span className="clear-icon"><Shield size={30} aria-hidden="true" /></span>
      <h3>No modeled attack path from the internet</h3>
      <p>Resources may have relationships without being internet-reachable.</p>
      <div className="node-inventory">{snapshot.graph.nodes.filter(n => n.id !== 'INTERNET').map(node =>
        <span key={node.id}><NodeIcon type={node.type} />{node.name}</span>)}</div>
    </div>}
    {!compact && <><label className="path-select">Inspect any graph node<select value={selectedNode} onChange={e => setSelectedNode(e.target.value)}><option value="">Choose a resource</option>{snapshot.graph.nodes.map(node => <option value={node.id} key={node.id}>{node.name} · {node.type}</option>)}</select></label>
      {inspected && <section className="node-inspector" aria-label="Selected node evidence"><h3>{inspected.name}</h3><code>{inspected.id}</code><p>{inspected.type} · engine risk: {inspected.risk} · {inspected.sensitive ? 'marked sensitive' : 'not marked sensitive'}</p><p>{path?.nodes.includes(inspected.id) ? 'On the selected attack path.' : 'Outside the selected attack path. This does not establish safety.'}</p>{snapshot.graph.edges.filter(edge => edge.source === inspected.id || edge.target === inspected.id).map((edge, index) => <Evidence key={`${edge.source}-${edge.target}-${index}`} edge={edge} index={index} />)}</section>}
    </>}
    {!compact && <details className="all-relationships">
      <summary>Inspect all graph relationships ({snapshot.graph.edges.length})</summary>
      <p className="muted">Includes relationships outside the selected path. Each arrow is an engine-reported edge.</p>
      {snapshot.graph.edges.map((edge, i) => <Evidence key={`${edge.source}-${edge.target}`} edge={edge} index={i} />)}
      {!snapshot.graph.edges.length && <p>No modeled relationships in this snapshot.</p>}
    </details>}
    <div className="graph-footer"><span>{snapshot.graph.nodes.length} nodes · {snapshot.graph.edges.length} relationships</span><span>Static analysis · No infrastructure access</span></div>
  </div>;
}
