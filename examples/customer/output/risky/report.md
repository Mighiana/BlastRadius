<!-- blastradius-report -->
## BlastRadius Security Check

**Decision: 🚫 BLOCK CHANGE**

**Security score:** 100 → 20
**New critical attack paths:** 1
**Newly reachable sensitive resources:** 1
**Newly internet-reachable resources:** 3

**Attack path:**
- Internet → Sample Web → Web Server → Sample App → Blastradius Synthetic Customer Data → Sensitive Data

**Responsible infrastructure change:**
cidr\_blocks = \["10.0.0.0/24"\] -&gt; cidr\_blocks = \["0.0.0.0/0"\]

**Policy:**
- New critical attack paths are prohibited
- New sensitive resource exposure is prohibited
- New public administrative ingress (SSH/RDP/all ports) is prohibited

**Recommendation:**
Restrict the public ingress CIDR before merging.

Analysis coverage: complete within documented model

_Simplified static AWS model, not proof of infrastructure safety. Unsupported relationships and unknown values can hide paths. No AWS access or deployment._