import { z } from 'zod';

const score = z.object({ before: z.number(), after: z.number(), delta: z.number() });
const edge = z.object({
  source: z.string(), target: z.string(), relationship: z.string(), reason: z.string(),
  evidence: z.string(), severity: z.string(), terraform_resource: z.string(),
  metadata: z.record(z.string(), z.unknown()).optional(),
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
  score_breakdown: z.array(z.object({ finding: z.string(), count: z.number(), points: z.number() })),
  exposed_resources: z.array(z.string()), reachable_sensitive: z.array(z.string()),
  attack_paths: z.array(path), graph: z.object({ nodes: z.array(node), edges: z.array(edge) }),
});
export const reportSchema = z.object({
  schema_version: z.literal(1), decision: z.string(), passed: z.boolean(),
  headline: z.string(), verdict: z.string(), score, before: snapshot, after: snapshot,
  new_attack_paths: z.array(path), removed_attack_paths: z.array(path),
  new_critical_paths: z.array(path), removed_critical_paths: z.array(path),
  newly_exposed: z.array(z.string()), newly_reachable_sensitive: z.array(z.string()),
  new_nodes: z.array(z.string()), removed_nodes: z.array(z.string()),
  new_edges: z.array(edge), removed_edges: z.array(edge),
  findings: z.array(z.object({ label: z.string(), detail: z.string(), delta: z.number(), severity: z.string() })),
  responsible_change: z.string(), responsible_changes: z.array(z.object({ file: z.string(), diff: z.string() })),
  diagnostics: z.array(z.object({ code: z.string(), severity: z.string(), message: z.string() })),
  limitations: z.array(z.string()),
  remediation: z.object({
    recommendations: z.array(z.object({
      title: z.string(), detail: z.string(), current: z.string(), recommended: z.string(),
      severity: z.string(), resource: z.string(),
    })),
    patched_files: z.record(z.string(), z.string()), diff: z.string(), can_autofix: z.boolean(),
  }),
  reports: z.object({ markdown: z.string(), sarif: z.record(z.string(), z.unknown()) }),
  demo: z.object({
    scenario_id: z.string(), stage: z.enum(['safe', 'risky', 'remediated']),
    remediation_kind: z.string(), note: z.string(),
  }).optional(),
});
const usage = z.object({
  period: z.string(), analyses: z.number(), plan: z.string(),
  limits: z.object({ analyses_per_month: z.number(), projects: z.number(), members: z.number() }),
});
const organization = z.object({
  id: z.string(), name: z.string(), role: z.enum(['owner', 'member', 'viewer']), plan: z.string(), usage,
});
export const sessionSchema = z.object({
  authenticated: z.boolean(),
  user: z.object({ id: z.string(), name: z.string(), email: z.string() }).nullable(),
  organizations: z.array(organization), csrf_token: z.string(),
  auth: z.object({ enabled: z.boolean(), mode: z.enum(['disabled', 'demo', 'oidc']), login_url: z.string().nullable() }),
  billing: z.object({ enabled: z.boolean(), test_mode: z.boolean() }),
});
export const projectSchema = z.object({
  id: z.string(), organization_id: z.string(), name: z.string(), created_at: z.number(),
});
export const jobSchema = z.object({
  id: z.string(), project_id: z.string(), organization_id: z.string(),
  base_label: z.string(), candidate_label: z.string(), created_at: z.number(),
  started_at: z.number().nullable(), completed_at: z.number().nullable(),
  status: z.enum(['queued', 'running', 'succeeded', 'failed']), error: z.string().nullable(),
  result: reportSchema.nullable().optional(),
  summary: z.object({ decision: z.string(), score, verdict: z.string() }).optional(),
});
export const scenariosSchema = z.object({
  scenarios: z.array(z.object({
    id: z.string(), title: z.string(), root_cause: z.string(), change: z.string(), stages: z.array(z.string()),
  })),
});
export const billingSchema = z.object({
  enabled: z.boolean(), test_mode: z.boolean(), plan: z.string(), subscription_status: z.string(), usage,
});
export type Report = z.infer<typeof reportSchema>;
export type Snapshot = z.infer<typeof snapshot>;
export type Edge = z.infer<typeof edge>;
export type Session = z.infer<typeof sessionSchema>;
export type Organization = z.infer<typeof organization>;
export type Job = z.infer<typeof jobSchema>;
export type Project = z.infer<typeof projectSchema>;
export type Stage = 'safe' | 'risky' | 'remediated';
export type AnalysisInput = {
  project_id: string; base_label: string; candidate_label: string;
} & ({ before_files: Record<string, string>; after_files: Record<string, string> } | { plan: Record<string, unknown> });

const errorMessages: Record<string, string> = {
  invalid_request: 'Check the input format, filenames and required fields.',
  csrf_required: 'Your session changed. Refresh your session, then try again.',
  use_billing_portal: 'A subscription already exists. Use the billing portal to manage it.',
  billing_customer_missing: 'No billing customer exists yet. Start with a test checkout.',
  analysis_timeout: 'The analysis exceeded its time limit. Try a smaller Terraform scope.',
  resource_limit_exceeded: 'The input exceeds the resource limit. Split it into smaller scopes.',
  invalid_analysis_input: 'The engine could not analyze this input. Check your HCL or Terraform plan.',
  server_restarted: 'The service restarted during analysis. Submit a new analysis.',
  analysis_failed: 'Analysis failed. Review the input and try again.',
  worker_failed: 'The analysis worker stopped. Try again with a smaller input.',
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
export async function mutate(url: string, method: 'POST' | 'DELETE', body?: unknown) {
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
export function safeBillingUrl(value: string) {
  const url = new URL(value);
  if (url.protocol !== 'https:' || !['checkout.stripe.com', 'billing.stripe.com'].includes(url.hostname) || url.port || url.username || url.password) {
    throw new Error('The billing redirect was rejected. Please contact the operator.');
  }
  return url.href;
}
