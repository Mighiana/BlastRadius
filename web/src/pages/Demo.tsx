import { useState } from 'react';
import { ArrowRight, RotateCcw, Wrench } from 'lucide-react';
import { reportSchema, scenariosSchema, type Stage } from '../api';
import { useResource } from '../hooks';
import { ReportView } from '../components/ReportView';
import { ErrorNotice, Loading, PageHeading } from '../components/UI';

export default function Demo() {
  const [scenario, setScenario] = useState('public_ssh');
  const [stage, setStage] = useState<Stage>('safe');
  const scenarios = useResource('/api/demo/scenarios', scenariosSchema);
  const result = useResource(`/api/demo/${encodeURIComponent(scenario)}?stage=${stage}`, reportSchema);
  const selected = scenarios.data?.scenarios.find(s => s.id === scenario);
  return <div className="container page">
    <PageHeading eyebrow="INTERACTIVE PRODUCT DEMO" title="A small diff. A new way in.">Follow a real Terraform change from safe baseline to exposed data, then close the path.</PageHeading>
    <div className="demo-console panel">
      <div className="scenario-list" role="group" aria-label="Demo scenario">{scenarios.data?.scenarios.map((s, index) =>
        <button className={`scenario ${s.id === scenario ? 'selected' : ''}`} key={s.id} aria-pressed={s.id === scenario}
          onClick={() => { setScenario(s.id); setStage('safe'); }}>
          <span className="scenario-index">0{index + 1}</span><span><strong>{s.title}</strong><small>{s.root_cause === 'network' ? 'Network exposure' : s.root_cause === 'identity' ? 'Identity & permissions' : 'Sensitive storage'}</small></span>
        </button>)}</div>
      <ErrorNotice error={scenarios.error} retry={scenarios.reload} />
      <div className="demo-controls"><div><span className="tag">REAL ENGINE · FIXED FIXTURES</span><p>{selected?.change ?? 'Loading scenario…'}</p></div>
        <div className="button-row">
          {stage !== 'safe' && <button className="button secondary" disabled={result.loading} onClick={() => setStage('safe')}><RotateCcw size={16} aria-hidden="true" />Reset baseline</button>}
          {stage === 'safe' || stage === 'remediated' ? <button className="button primary" disabled={result.loading || !result.data} onClick={() => setStage('risky')}>Simulate risky change<ArrowRight size={17} aria-hidden="true" /></button>
            : <button className="button primary" disabled={result.loading || !result.data} onClick={() => setStage('remediated')}><Wrench size={17} aria-hidden="true" />{scenario === 'broad_iam' ? 'Restore least-privilege fixture' : 'Remediate & re-analyze'}</button>}
        </div>
      </div>
      <ol className="steps" aria-label="Demo progress">
        {(['safe', 'risky', 'remediated'] as const).map((item, i) => <li key={item} aria-current={stage === item ? 'step' : undefined}><span>0{i + 1}</span>{['Safe baseline', 'Simulate & explain', 'Remediate & verify'][i]}</li>)}
      </ol>
    </div>
    <ErrorNotice error={result.error} retry={result.reload} />
    {result.loading && <Loading>Running the selected comparison…</Loading>}
    {result.data && <ReportView key={`${scenario}-${stage}`} report={result.data} />}
    <p className="footnote">Each stage is computed by the Python engine at service startup from controlled Terraform fixtures. No AWS credentials, provider execution or cloud changes.</p>
  </div>;
}
