import { z } from 'zod';

const text = (max: number) => z.string().trim().max(max).refine(value => [...value].every(character => {
  const code = character.charCodeAt(0);
  return code === 10 || (code >= 32 && code !== 127);
}), 'Use plain text without control characters.');
export const betaPrivacySchema = z.object({
  version: z.string().min(1), retention_days: z.number().int().positive(), notice: z.string().min(1),
});
export const betaInputSchema = z.object({
  name: text(100).pipe(z.string().min(1)), email: text(320).pipe(z.email()),
  company: text(120).optional(), role: text(80).optional(),
  team_size: z.number().int().min(1).max(100000).nullable().optional(),
  repository_count: z.number().int().min(0).max(100000).nullable().optional(),
  primary_cloud: z.enum(['aws', 'azure', 'gcp', 'multiple', 'other', 'none']).nullable().optional(),
  source_control: z.enum(['github', 'gitlab', 'both', 'other', 'none']).nullable().optional(),
  problem: text(1000).optional(), privacy_version: z.string().min(1), privacy_consent: z.literal(true),
}).strict();
export const betaStoredSchema = z.object({ status: z.literal('stored'), message: z.string() });
export const feedbackInputSchema = z.object({ useful: z.boolean(), message: text(1000) }).strict();
export const feedbackSchema = z.object({
  id: z.string(), analysis_id: z.string(), project_id: z.string(), organization_id: z.string(),
  user_id: z.string(), useful: z.boolean(), message: z.string().max(1000),
  created_at: z.number(), updated_at: z.number(),
});
export const feedbackResponseSchema = z.object({ feedback: feedbackSchema.nullable() });
export const feedbackSavedSchema = z.object({ feedback: feedbackSchema });
