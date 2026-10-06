import type { Report } from '../api';

export type Diagnostic = Report['diagnostics'][number];

export const CODE_LABEL: Record<string, string> = {
  UNSUPPORTED_RESOURCE: 'Resource types outside coverage',
  UNEXPANDED_MODULE: 'Modules not expanded',
  UNEXPANDED_RESOURCE: 'count / for_each / dynamic not expanded',
  UNRESOLVED_EXPRESSION: 'Values computed at plan time',
  UNRESOLVED_RELATIONSHIP: 'References to unmodeled resources',
  EXTERNAL_POLICY: 'Managed IAM policy content unavailable',
  INVALID_POLICY: 'IAM policy not evaluable',
  IAM_POLICY_EXPRESSION_UNRESOLVED: 'IAM policy not evaluable',
  UNMODELED_SG_HOP: 'Security-group-to-security-group traffic',
};
export const CODE_HELP: Record<string, string> = {
  UNSUPPORTED_RESOURCE: 'These types are not in the reachability model. They cannot create a modeled path, but they can hide one.',
  UNEXPANDED_MODULE: 'module blocks are not downloaded or expanded. Point BlastRadius at the root that declares the resources.',
  UNEXPANDED_RESOURCE: 'Resources built from loops are not enumerated, so their rules and links are unknown.',
  UNRESOLVED_EXPRESSION: 'Security-relevant attributes (tags, CIDRs, policies) use variables, locals or functions. Use plan JSON to analyze resolved values.',
  UNRESOLVED_RELATIONSHIP: 'A modeled resource links to something outside coverage, so the link cannot be followed.',
  EXTERNAL_POLICY: "Attached policy ARNs are not resolved, so the role's permissions are unknown.",
  INVALID_POLICY: 'The policy document is templated or not literal JSON.',
  IAM_POLICY_EXPRESSION_UNRESOLVED: 'The policy document is templated or not literal JSON.',
  UNMODELED_SG_HOP: 'SG-to-SG ingress is not modeled.',
};
export const UNSUPPORTED_RESOURCE_HELP = CODE_HELP.UNSUPPORTED_RESOURCE!;
const MODULE_MARKER = '(module/indexed address not modeled)';

export function blockingDiagnosticGroups(diagnostics: Diagnostic[]): Array<[string, Diagnostic[]]> {
  const groups = new Map<string, Diagnostic[]>();
  for (const diagnostic of diagnostics) {
    if (diagnostic.blocks_analysis !== true) continue;
    const group = groups.get(diagnostic.code);
    if (group) group.push(diagnostic); else groups.set(diagnostic.code, [diagnostic]);
  }
  return [...groups].sort(([codeA, a], [codeB, b]) => b.length - a.length || codeA.localeCompare(codeB));
}

/** Splits UNSUPPORTED_RESOURCE diagnostics into unique module/indexed addresses and unique resource types. */
export function unsupportedBreakdown(diagnostics: Diagnostic[]) {
  const subject = (message: string) => message.split(': ').at(-1) ?? message;
  const moduleAddresses = [...new Set(diagnostics
    .filter(diagnostic => diagnostic.message.includes(MODULE_MARKER))
    .map(diagnostic => subject(diagnostic.message).replace(/\s+\(module\/indexed address not modeled\)\s*$/, '')))];
  const types = [...new Set(diagnostics
    .filter(diagnostic => !diagnostic.message.includes(MODULE_MARKER))
    .map(diagnostic => subject(diagnostic.message).replace(/\s+\([^)]*\)\s*$/, '')))];
  return { moduleAddresses, types };
}

/** Short `[count, label]` entries for each blocking coverage category. */
export function coverageGapChips(groups: Array<[string, Diagnostic[]]>): Array<[number, string]> {
  return groups.flatMap(([code, diagnostics]): Array<[number, string]> => {
    if (code !== 'UNSUPPORTED_RESOURCE') return [[diagnostics.length, CODE_LABEL[code] ?? code]];
    const { moduleAddresses, types } = unsupportedBreakdown(diagnostics);
    const chips: Array<[number, string]> = [];
    if (moduleAddresses.length) chips.push([moduleAddresses.length, 'Module or indexed resources not modeled']);
    if (types.length) chips.push([types.length, CODE_LABEL.UNSUPPORTED_RESOURCE!]);
    return chips;
  });
}
