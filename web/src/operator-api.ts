import { z } from 'zod';
import { usageSchema } from './api';
import { betaInputSchema, feedbackSchema } from './beta-api';

export const eventNames = [
  'account_created', 'workspace_created', 'project_created', 'analysis_started', 'analysis_completed',
  'analysis_failed', 'block_result', 'review_result', 'safe_result', 'report_exported', 'github_connected',
  'beta_interest_submitted', 'feedback_submitted',
] as const;
export const eventSummarySchema = z.object({
  retention_days: z.number().int().positive(), max_records: z.number().int().positive(),
  active_workspaces: z.number().int().nonnegative(),
  counts: z.record(z.enum(eventNames), z.number().int().nonnegative()),
});
export type OperatorPage = {
  items: Record<string, unknown>[]; limit: number; offset: number; next_offset: number | null;
};
function page<T extends z.ZodRawShape>(row: z.ZodObject<T>): z.ZodType<OperatorPage> {
  return z.object({
    items: z.array(row).max(100), limit: z.number().int().min(1).max(100),
    offset: z.number().int().min(0).max(1000000), next_offset: z.number().int().min(1).max(1000100).nullable(),
  });
}
const usage = usageSchema.extend({ id: z.string(), created_at: z.number() });
export const operatorSchemas = {
  users: page(z.object({ id: z.string(), email_verified: z.boolean(), created_at: z.number() })),
  organizations: page(usage), usage: page(usage),
  projects: page(z.object({ id: z.string(), organization_id: z.string(), archived_at: z.number().nullable(), created_at: z.number() })),
  failures: page(z.object({
    id: z.string(), organization_id: z.string(), project_id: z.string(), status: z.literal('failed'),
    error: z.enum(['analysis_failed', 'analysis_timeout', 'dispatch_failed', 'github_analysis_failed',
      'invalid_analysis_input', 'invalid_worker_result', 'resource_limit_exceeded', 'result_too_large',
      'server_restarted', 'service_lease_lost', 'worker_failed']).catch('analysis_failed'),
    created_at: z.number(), completed_at: z.number().nullable(),
  })),
  'beta-requests': page(betaInputSchema.omit({ privacy_consent: true }).extend({ id: z.string(), created_at: z.number() }).strip()),
  feedback: page(feedbackSchema),
};
export type OperatorList = keyof typeof operatorSchemas;
