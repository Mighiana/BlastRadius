<!-- blastradius-report -->
## BlastRadius Security Check

**Decision: ⚠ REVIEW REQUIRED**

**Security score:** 100 → 100
**New critical attack paths:** 0
**Newly reachable sensitive resources:** 0
**Newly internet-reachable resources:** 0

No new modeled critical attack paths detected.

**Responsible infrastructure change:**
0 line(s) removed, 4 line(s) added

**Policy:**
- Analysis incomplete: resolve coverage diagnostics before treating this change as safe.

**Recommendation:**
Resolve coverage diagnostics and re-analyze; missing paths do not establish safety.

Analysis coverage: INCOMPLETE
- after [UNEXPANDED_MODULE] main.tf: HCL modules are not downloaded or expanded.

_Simplified static AWS model, not proof of infrastructure safety. Unsupported relationships and unknown values can hide paths. No AWS access or deployment._