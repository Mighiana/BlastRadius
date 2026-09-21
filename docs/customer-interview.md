# Customer discovery interview

Internal research guide. We are testing whether the problem, proposed evidence
and buying process fit a real workflow. Interest in a demo is not a purchase
commitment. Record contradictory evidence and “not useful” responses.

Ask permission to take notes. Record only agreed, non-sensitive details; do not
request private Terraform, credentials or incident records. Ask about recent
examples before describing BlastRadius. Use “What happened next?” and “Can you
give an example?” as neutral follow-ups. Do not suggest an answer or defend the
product when the respondent disagrees.

## Current workflow, before the demo

1. What is your role, and which infrastructure changes do you review yourself?
2. Walk me through the last Terraform PR your team reviewed, from authoring to
   merge. What information did each reviewer use?
3. Who reviews infrastructure-security changes? How does responsibility change
   for networking, identity and data storage?
4. Which tools and manual checks do you currently use? What decisions does each
   one help you make, and where does it add work?
5. What causes the most false positives or review noise? Describe the last one
   and how you determined it was incorrect or unhelpful.
6. Has an infrastructure change ever created unexpected exposure, or not?
   If yes, how was it discovered and what changed afterward? A hypothetical or
   sanitized example is enough; do not share confidential incident details.
7. For a recent routine change and a difficult one, how long did security review
   take? How much was active work versus waiting? How do you know?
8. Which relationships are hardest to verify from your Terraform inputs?
   What important controls or infrastructure live outside that repository?

## Reaction to the evidence

Show the [synthetic sample](customer-samples.md), including model limits and a
REVIEW result. Let the respondent interpret it before explaining your conclusion.

9. What does this result tell you? What does it leave unanswered?
10. Would comparing modeled attack paths between revisions help any part of your
    current process? Where would it add no value or duplicate another tool?
11. Which evidence would you need to verify or challenge a reported path?
12. Under what conditions, if any, would you trust an automated merge gate?
    What would make you stop using it?
13. Which findings should block automatically, which need review, and which
    should remain informational? Ask for examples and the reason for each.
14. How should an incomplete analysis affect merging? Who would own exceptions,
    how would they be documented, and what should happen when they expire?
15. If a proposed patch removed this modeled path, what further checks would
    your team require before accepting it?

## Adoption and purchasing

16. Where could a tool like this run in your organization? Would it need to be
    self-hosted, or could another deployment model work? What policy drives that?
17. What information could leave your environment, and who approves that?
    What would retention, deletion, identity or repository-permission review require?
18. Who would evaluate this, use it regularly, approve its security review and
    approve a purchase? Are those different people?
19. What would make you pay for it, if anything? What measured outcome or
    capability would justify a budget rather than your current approach?
20. How do you budget for comparable tools today? If comfortable sharing a
    range, what is it based on? Do not introduce a price anchor first.
21. What would an evaluation have to demonstrate? Which authorized, sanitized
    examples would represent both useful findings and unacceptable noise?
22. What reasons might prevent adoption even if the evaluation works?
23. Is there anything we should have asked? May we follow up, and through
    which existing channel? Declining follow-up is fine.

## Notes and interpretation

Record role/context, current workflow, concrete examples, current alternatives,
the respondent's own success criteria, objections, approval roles and agreed
next step. Separate direct quotations, observed behavior and interviewer
interpretation. Note unknowns instead of filling them in.

After several conversations, compare recurring problems and counterexamples
against the [persona hypotheses](buyer-personas.md). Do not infer a market size,
conversion rate or willingness to pay from a small convenience sample. Update
hypotheses when evidence contradicts them; avoid turning leading demo questions
into customer endorsements.
