import type { Report, Session } from '../api';

export const session: Session = {
  authenticated: false, user: null, organizations: [], csrf_token: 'test-csrf',
  auth: { enabled: true, mode: 'demo', public_url: window.location.origin, login_url: null }, billing: { enabled: false, test_mode: true },
};
const edges = [{
  source: 'INTERNET', target: 'aws_s3_bucket.customer_data', relationship: 'public access',
  reason: 'Public bucket ACL grants access.', evidence: 'acl = "public-read"',
  severity: 'CRITICAL', terraform_resource: 'aws_s3_bucket.customer_data',
}];
const nodes = [
  { id: 'INTERNET', name: 'Internet', type: 'INTERNET', sensitive: false, risk: 'NONE' },
  { id: 'aws_s3_bucket.customer_data', name: 'Customer Data', type: 'S3_BUCKET', sensitive: true, risk: 'CRITICAL' },
];
const path = {
  id: 'public-path', nodes: nodes.map(n => n.id), labels: nodes.map(n => n.name),
  edges, severity: 'CRITICAL', explanation: 'Public access reaches sensitive storage.', reaches_sensitive: true,
};
const before = {
  label: 'baseline', score: 100, risk_level: 'LOW', score_breakdown: [],
  exposed_resources: [], reachable_sensitive: [], attack_paths: [], graph: { nodes, edges: [] },
};
export const risky: Report = {
  schema_version: 1, decision: 'BLOCK CHANGE', passed: false, headline: 'Sensitive data became reachable.',
  verdict: 'SECURITY REGRESSION', score: { before: 100, after: 35, delta: -65 }, before,
  after: { ...before, label: 'risky', score: 35, risk_level: 'CRITICAL', attack_paths: [path], graph: { nodes, edges },
    exposed_resources: ['aws_s3_bucket.customer_data'], reachable_sensitive: ['aws_s3_bucket.customer_data'],
    score_breakdown: [{ finding: 'Public storage', count: 1, points: -20 }] },
  new_attack_paths: [path], removed_attack_paths: [], new_critical_paths: [path], removed_critical_paths: [],
  new_nodes: [], removed_nodes: [], new_edges: edges, removed_edges: [],
  newly_exposed: ['aws_s3_bucket.customer_data'], newly_reachable_sensitive: ['aws_s3_bucket.customer_data'],
  findings: [{ label: 'Sensitive storage', detail: 'Newly reachable.', delta: 1, severity: 'CRITICAL' }],
  responsible_change: 'Bucket ACL changed.', responsible_changes: [{ file: 'main.tf', diff: '- acl = "private"\n+ acl = "public-read"' }],
  diagnostics: [{ code: 'model_limitations', severity: 'info', message: 'Simplified static model.' }],
  limitations: ['No path is not proof of safety.'],
  remediation: { recommendations: [], patched_files: { 'main.tf': 'acl = "private"' }, diff: '- public-read\n+ private', can_autofix: true },
  reports: { markdown: '# Report', sarif: { version: '2.1.0' } },
};
export const safe: Report = {
  ...risky, decision: 'SAFE TO MERGE', passed: true, headline: 'No new modeled critical paths.',
  score: { before: 100, after: 100, delta: 0 }, after: before, new_attack_paths: [],
  new_critical_paths: [], newly_reachable_sensitive: [], newly_exposed: [],
};
