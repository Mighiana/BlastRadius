import { z } from 'zod';

const score = z.object({ before: z.number(), after: z.number(), delta: z.number() });
const edge = z.object({
  source: z.string(), target: z.string(), relationship: z.string(), reason: z.string(),
  evidence: z.string(), severity: z.string(), terraform_resource: z.string(),
  metadata: z.record(z.string(), z.unknown()).optional(),
  confidence: z.string().optional(), category: z.string().optional(),
  source_file: z.string().optional(), remediation: z.string().optional(),
});
const node = z.object({
  id: z.string(), name: z.string(), type: z.string(), sensitive: z.boolean(), risk: z.string(),
});
const path = z.object({
  id: z.string(), nodes: z.array(z.string()), labels: z.array(z.string()),
  edges: z.array(edge), severity: z.string(), explanation: z.string(), reaches_sensitive: z.boolean(),
});
const snapshot = z.object({
  label: z.string(), score: z.number(), risk_level: z.string(),
  complete: z.boolean().optional(), paths_truncated: z.boolean().optional(), path_work: z.number().optional(),
  score_breakdown: z.array(z.object({ finding: z.string(), count: z.number(), points: z.number() })),
  exposed_resources: z.array(z.string()), reachable_sensitive: z.array(z.string()),
  attack_paths: z.array(path), graph: z.object({ nodes: z.array(node), edges: z.array(edge) }),
});
export const reportSchema = z.object({
  schema_version: z.literal(1), decision: z.string(), passed: z.boolean(),
  analysis_complete: z.boolean().optional(),
  headline: z.string(), verdict: z.string(), score, before: snapshot, after: snapshot,
  new_attack_paths: z.array(path), removed_attack_paths: z.array(path),
  new_critical_paths: z.array(path), removed_critical_paths: z.array(path),
  newly_exposed: z.array(z.string()), newly_reachable_sensitive: z.array(z.string()),
  new_nodes: z.array(z.string()), removed_nodes: z.array(z.string()),
  new_edges: z.array(edge), removed_edges: z.array(edge),
  findings: z.array(z.object({ label: z.string(), detail: z.string(), delta: z.number(), severity: z.string() })),
  responsible_change: z.string(), responsible_changes: z.array(z.object({ file: z.string(), diff: z.string() })),
  diagnostics: z.array(z.object({
    code: z.string(), severity: z.string(), message: z.string(),
    phase: z.string().optional(), resource: z.string().optional(),
    attribute: z.string().optional(), source_file: z.string().optional(), blocks_analysis: z.boolean().optional(),
  })),
  limitations: z.array(z.string()),
  remediation: z.object({
    recommendations: z.array(z.object({
      title: z.string(), detail: z.string(), current: z.string(), recommended: z.string(),
      severity: z.string(), resource: z.string(),
    })),
    patched_files: z.record(z.string(), z.string()), diff: z.string(), can_autofix: z.boolean(),
  }),
  reports: z.object({ markdown: z.string(), sarif: z.record(z.string(), z.unknown()).optional() }),
  demo: z.object({
    scenario_id: z.string(), stage: z.enum(['safe', 'risky', 'remediated']),
    remediation_kind: z.string(), note: z.string(),
  }).optional(),
});
export const limitsSchema = z.object({
  analyses_per_month: z.number(), projects: z.number(), members: z.number(), retention_days: z.number(),
});
export const featuresSchema = z.object({
  advanced_policy: z.boolean(), sarif: z.boolean(), team: z.boolean(), organization_policy: z.boolean(),
  audit: z.boolean(), json: z.boolean(), markdown: z.boolean(), payments: z.literal(false),
  priority_queue: z.boolean(), saml: z.boolean(),
});
export const usageSchema = z.object({
  period: z.string(), analyses: z.number(), plan: z.string(), exports: z.number(),
  projects: z.number(), members: z.number(), pending_invitations: z.number(),
  limits: limitsSchema, features: featuresSchema,
});
export const roleSchema = z.enum(['owner', 'admin', 'developer', 'viewer']);
const organization = z.object({
  id: z.string(), name: z.string(), role: roleSchema, plan: z.string(), usage: usageSchema,
});
export const sessionSchema = z.object({
  authenticated: z.boolean(),
  capabilities: z.object({ platform_admin: z.boolean() }).optional(),
  user: z.object({ id: z.string(), name: z.string(), email: z.string(), email_verified: z.boolean(), created_at: z.number() }).nullable(),
  organizations: z.array(organization), csrf_token: z.string(),
  auth: z.object({ enabled: z.boolean(), mode: z.enum(['disabled', 'demo', 'oidc']), public_url: z.string().url(), login_url: z.string().nullable() }),
  billing: z.object({ enabled: z.literal(false), mode: z.literal('commercial_beta') }),
});
export const projectSchema = z.object({
  id: z.string(), organization_id: z.string(), name: z.string(), created_at: z.number(),
  description: z.string(), repository: z.string(), repository_provider: z.enum(['manual', 'github']),
  default_branch: z.string(), environment: z.string(), terraform_root: z.string(),
  archived_at: z.number().nullable(), updated_at: z.number().nullable(),
});
export const policySchema = z.object({
  version: z.literal(1),
  gate: z.object({ block_new_critical_paths: z.boolean(), block_new_sensitive_exposure: z.boolean(), block_public_admin_ports: z.boolean() }),
  allowed: z.object({ public_https: z.boolean() }),
  thresholds: z.object({ minimum_security_score: z.number().int().min(0).max(100).nullable() }),
});
export const policySnapshotSchema = z.object({
  source: z.string(), version: z.number(), rules: policySchema.nullable(),
});
export const policyResponseSchema = z.object({
  policy: policySchema.nullable(), version: z.number(), effective: policySnapshotSchema.optional(),
});
export const jobSchema = z.object({
  id: z.string(), project_id: z.string(), organization_id: z.string(),
  base_label: z.string(), candidate_label: z.string(), created_at: z.number(),
  started_at: z.number().nullable(), completed_at: z.number().nullable(),
  status: z.enum(['queued', 'running', 'succeeded', 'failed']), error: z.string().nullable(),
  input_type: z.enum(['hcl', 'plan', 'github']).nullable(),
  base_ref: z.string().nullable(), candidate_ref: z.string().nullable(),
  base_sha: z.string().nullable(), candidate_sha: z.string().nullable(),
  decision: z.string().nullable(), policy_snapshot: policySnapshotSchema.nullable(),
  result: reportSchema.nullable().optional(),
  summary: z.object({ decision: z.string(), score, verdict: z.string() }).optional(),
});
export const scenariosSchema = z.object({
  scenarios: z.array(z.object({
    id: z.string(), title: z.string(), root_cause: z.string(), change: z.string(), stages: z.array(z.string()),
  })),
});
export const plansSchema = z.object({
  payments_enabled: z.literal(false), mode: z.literal('commercial_beta'),
  plans: z.array(z.object({
    code: z.string(), monthly_price_usd: z.number().nullable(), price_status: z.string(),
    assignment: z.enum(['signup', 'operator_beta']), limits: limitsSchema, features: featuresSchema, configurable: z.boolean(),
  })),
});
export const projectsSchema = z.object({ projects: z.array(projectSchema) });
export const historySchema = z.object({ analyses: z.array(jobSchema), total: z.number(), limit: z.number(), offset: z.number() });
export const sessionsSchema = z.object({ sessions: z.array(z.object({
  id: z.string(), created_at: z.number().nullable(), expires_at: z.number(), current: z.boolean(),
})) });
export const membersSchema = z.object({ members: z.array(z.object({
  user_id: z.string(), name: z.string(), email: z.string(), role: roleSchema,
})) });
const invitationSchema = z.object({
  id: z.string(), organization_id: z.string(), email: z.string(), role: roleSchema,
  created_at: z.number(), expires_at: z.number(), revoked_at: z.number().nullable(), accepted_at: z.number().nullable(),
});
export const invitationsSchema = z.object({ invitations: z.array(invitationSchema) });
export const createdInvitationSchema = invitationSchema.extend({ invitation_url: z.string().url(), delivery: z.literal('manual') });
export const acceptedInvitationSchema = z.object({ organization_id: z.string(), role: roleSchema });
export const auditSchema = z.object({ events: z.array(z.object({
  id: z.string(), actor: z.string().nullable(), action: z.string(), target_id: z.string().nullable(),
  details: z.record(z.string(), z.unknown()), created_at: z.number(),
})) });
export const githubConfigSchema = z.object({
  configured: z.boolean(), available: z.boolean(), mode: z.literal('operator_registration'), self_service: z.literal(false),
  app_slug: z.string().nullable(), installation_url: z.string().nullable(), reason: z.string(),
  permissions: z.record(z.string(), z.string()),
});
export const installationsSchema = z.object({ installations: z.array(z.object({
  id: z.number().int(), account_id: z.number().int(), account_login: z.string(), status: z.string(), verified_at: z.number(),
})) });
export const githubProjectSchema = z.object({
  connection: z.object({
    id: z.string(), installation_id: z.number().int(), repository_id: z.number().int(),
    full_name: z.string(), status: z.enum(['active', 'revoked', 'disconnected']), created_at: z.number(),
  }).nullable(),
  latest_run: z.object({
    id: z.string(), analysis_id: z.string().nullable(), pull_number: z.number().int(),
    base_sha: z.string(), head_sha: z.string(), base_ref: z.string(), head_ref: z.string(),
    head_repository_id: z.number().int(), status: z.string(), error: z.string().nullable(), check_id: z.number().int().nullable(),
  }).nullable(),
});
export type Report = z.infer<typeof reportSchema>;
export type Snapshot = z.infer<typeof snapshot>;
export type Edge = z.infer<typeof edge>;
export type Session = z.infer<typeof sessionSchema>;
export type Organization = z.infer<typeof organization>;
export type Job = z.infer<typeof jobSchema>;
export type Project = z.infer<typeof projectSchema>;
export type Policy = z.infer<typeof policySchema>;
export type Role = z.infer<typeof roleSchema>;
export function canManage(role?: Role) { return role === 'owner' || role === 'admin'; }
export function canAnalyze(role?: Role) { return canManage(role) || role === 'developer'; }
export type Stage = 'safe' | 'risky' | 'remediated';
export type AnalysisInput = {
  project_id: string; base_label: string; candidate_label: string;
} & ({ before_files: Record<string, string>; after_files: Record<string, string> } | { plan: Record<string, unknown> });

const errorMessages: Record<string, string> = {
  platform_admin_required: 'Platform operator access is required. Workspace roles do not grant this access.',
  submission_storage_full: 'Submissions are temporarily unavailable. Contact your deployment operator through your established channel.',
  analysis_not_terminal: 'Wait for this analysis to finish before sending feedback.',
  feedback_expired: 'This feedback has expired and cannot be edited.',
  body_too_large: 'This submission is too large. Shorten the text and try again.',
  invalid_request: 'Check the input format, filenames and required fields.',
  csrf_required: 'Your session changed. Refresh your session, then try again.',
  invalid_origin: 'This address does not match the server’s trusted origin. Ask the operator to set BR_PUBLIC_URL to this site’s exact origin, including scheme and port, then restart the service.',
  insufficient_role: 'Your workspace role does not allow this action. Ask a workspace owner for access.',
  organization_limit_exceeded: 'You already own the maximum of five workspaces. Use an existing workspace.',
  invitation_unavailable: 'This invitation is unavailable. Sign in with the verified email it was sent to, or ask a workspace manager for a new link.',
  last_owner: 'The last owner cannot be removed or demoted. Promote another member first.',
  sarif_not_entitled: 'Saved SARIF exports require an operator-granted Pro, Team or Enterprise plan. Public demo exports remain available.',
  advanced_policy_not_entitled: 'Project policy editing requires an operator-granted Pro, Team or Enterprise plan.',
  organization_policy_not_entitled: 'Workspace policies require Team or Enterprise.',
  team_not_entitled: 'Invitations and role changes require Team or Enterprise.',
  audit_not_entitled: 'Audit visibility requires Team or Enterprise.',
  project_archived: 'Restore this project before starting a new analysis.',
  github_not_configured: 'The operator has not configured GitHub App credentials. Uploads and public demos remain available.',
  github_connection_unavailable: 'This connection is unavailable. Check installation status and restore archived projects first.',
  github_repository_unavailable: 'The GitHub App could not verify access to this repository. Ask the operator to check installation permissions.',
  analysis_timeout: 'The analysis exceeded its time limit. Try a smaller Terraform scope.',
  resource_limit_exceeded: 'The input exceeds the resource limit. Split it into smaller scopes.',
  invalid_analysis_input: 'The engine could not analyze this input. Check your HCL or Terraform plan.',
  server_restarted: 'The service restarted during analysis. Submit a new analysis.',
  analysis_failed: 'Analysis failed. Review the input and try again.',
  worker_failed: 'The analysis worker stopped. Try again with a smaller input.',
  invalid_worker_result: 'The analysis returned an invalid result. Submit a new analysis.',
  dispatch_failed: 'The analysis could not start. Submit a new analysis.',
  service_lease_lost: 'This service lost database ownership. Retry when the service is ready.',
  analysis_persistence_failed: 'Analysis incomplete: the service could not save an outcome. Ask the operator to restore database access and restart the service, then submit a new analysis.',
  result_too_large: 'The result is too large. Try a smaller Terraform scope.',
};
export function jobError(code: string | null) {
  return (code && errorMessages[code]) || 'The analysis could not be completed. Please try again.';
}
export class ApiError extends Error {
  constructor(public status: number, public code: string, public requestId: string | null) {
    const fallback: Record<number, string> = {
      401: 'Your session has expired. Sign in again.',
      403: 'This action is not permitted for your role or session.',
      404: 'This item is unavailable or you no longer have access.',
      402: 'Your workspace quota has been reached. Check usage and plans.',
      409: 'This action is not available in the current state.',
      413: 'The upload is too large. Keep the full request below 1 MiB and each snapshot at 30 files or fewer.',
      422: 'Check the input format and required fields.',
      429: 'Too many requests or the analysis queue is full. Wait a moment, then retry.',
      502: 'The provider is unavailable. Please try again later.',
      503: 'This service is not configured or is temporarily unavailable.',
    };
    super(errorMessages[code] || fallback[status] || 'The service could not complete this request.');
  }
}
let csrfToken = '';
export function setCsrf(token: string) { csrfToken = token; }

async function response(url: string, options: RequestInit = {}) {
  const headers = new Headers(options.headers);
  if (options.body) headers.set('Content-Type', 'application/json');
  if (options.method && options.method !== 'GET') headers.set('X-CSRF-Token', csrfToken);
  let res: Response;
  try {
    res = await fetch(url, { ...options, headers, credentials: 'same-origin', cache: 'no-store' });
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error;
    throw new Error('Cannot reach the API. Check your connection and that the service is running.');
  }
  if (!res.ok) {
    const body: unknown = await res.json().catch(() => null);
    const parsed = z.object({ detail: z.string() }).safeParse(body);
    const code = parsed.success ? parsed.data.detail : '';
    if (res.status === 401 || code === 'csrf_required') {
      window.dispatchEvent(new Event('br:session-refresh'));
    }
    throw new ApiError(res.status, code, res.headers.get('X-Request-ID'));
  }
  return res;
}
export async function request<T>(url: string, schema: z.ZodType<T>, options?: RequestInit): Promise<T> {
  const res = await response(url, options);
  const body: unknown = await res.json().catch(() => null);
  const parsed = schema.safeParse(body);
  if (!parsed.success) throw new Error('The API response is incompatible with this app. Please refresh or contact the operator.');
  return parsed.data;
}
export async function mutate(url: string, method: 'POST' | 'DELETE' | 'PATCH' | 'PUT', body?: unknown) {
  await response(url, { method, ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
}
export function download(content: BlobPart, filename: string, type = 'application/json') {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const anchor = document.createElement('a');
  anchor.href = url; anchor.download = filename; anchor.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
export async function exportReport(id: string, format: 'json' | 'markdown' | 'sarif') {
  const res = await response(`/api/analyses/${encodeURIComponent(id)}/report?format=${format}`);
  download(await res.blob(), `blastradius.${format === 'markdown' ? 'md' : format}`);
}
export function safeGitHubUrl(value: string) {
  const url = new URL(value);
  if (url.protocol !== 'https:' || url.hostname !== 'github.com' || url.port || url.username || url.password) {
    throw new Error('The GitHub link was rejected. Please contact the operator.');
  }
  return url.href;
}
