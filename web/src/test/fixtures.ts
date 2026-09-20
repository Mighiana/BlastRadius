import type { Job, Organization, Project, Report, Session } from '../api';

export const session: Session = {
  authenticated: false, user: null, organizations: [], csrf_token: 'test-csrf',
  auth: { enabled: true, mode: 'demo', public_url: window.location.origin, login_url: null }, billing: { enabled: false, mode: 'commercial_beta' },
};
export const organization: Organization = {
  id: 'org', name: 'Example', role: 'owner', plan: 'free', usage: {
    period: '2026-09', plan: 'free', analyses: 1, exports: 0, projects: 0, members: 1, pending_invitations: 0,
    limits: { analyses_per_month: 25, projects: 1, members: 1, retention_days: 7 },
    features: { advanced_policy: false, sarif: false, team: false, organization_policy: false, audit: false, json: true, markdown: true, payments: false, priority_queue: false, saml: false },
  },
};
export const account: Session = { ...session, authenticated: true, user: { id: 'owner', name: 'Owner', email: 'owner@example.test', email_verified: true, created_at: 1 }, organizations: [organization] };
export const project: Project = { id: 'project', organization_id: 'org', name: 'Infrastructure', created_at: 1, updated_at: null, description: '', repository: '', repository_provider: 'manual', default_branch: 'main', environment: '', terraform_root: '.', archived_at: null };
export const queued: Job = {
  id: 'job', project_id: 'project', organization_id: 'org', base_label: 'before', candidate_label: 'after',
  created_at: 1, started_at: null, completed_at: null, status: 'queued', error: null, result: null,
  input_type: 'hcl', base_ref: null, candidate_ref: null, base_sha: null, candidate_sha: null,
  decision: null, policy_snapshot: { source: 'default', version: 1, rules: null },
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
