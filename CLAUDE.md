
# DEPT® Anatomy of Code — Project Rules

This project is a teaching, certification, and reference system for DEPT®
architects and engineers, built around the CODE-CODER framework.

## Audience

Primary: architects and senior engineers across DEPT®'s Adobe Experience
Cloud practice. Secondary: IT generalists onboarding to the practice.
Audience is Indian and globally distributed. Most readers are in India.

## Language & voice discipline

- Indian English spelling: organise, optimise, behaviour, colour, centre.
- Plain professional English. No Americanisms ("y'all", "reach out",
  "circle back"), no overly British academic register, no Indian
  business-English clichés ("do the needful", "kindly", "revert back").
- Examples and references should land for an Indian reader: Razorpay,
  Shiprocket, UPI, DPDP, Aadhaar, BFSI, Flipkart, Myntra where relevant.
  Global examples (Stripe, Stripe Press, Linear, Figma) are fine when
  they're the right reference — don't force-localise.
- Acronyms expanded on first use (KYC, DPDP, AEMaaCS, CJA, AJO, LLMO).
- Crore/lakh acceptable when discussing Indian market context; otherwise
  use standard digit grouping.

## Content style — Path 3 (layered)

The course uses declarative, opinionated prose written for the architect.
That voice is the product. Do not bulletise the prose itself.

New content and revisions follow the LAYER pattern:
1. Scan Box at the top of each major section (3-5 bullets, ~30-second
   read covering "what / why / so what")
2. Existing prose underneath, untouched in voice
3. Diagrams and callout blocks woven through, not piled at the end

Scan boxes are for readers in a hurry. Prose is for readers who'll
architect from it.

## Diagram convention — hybrid

- ASCII (.arch-diagram, .arch-row, .arch-node) for static architecture:
  CODE-CODER framework, deployment layers, system topology, anything
  spatial.
- Mermaid for flows: pipelines, journeys, sequence diagrams, decision
  trees, testing workflows.
- Mermaid loaded once via CDN in the course HTML <head>.

## Callout block types

Reuse the existing .arch-review / blockquote design language. Four block
types in use:
- "Why This Matters" — the architect-level stake
- "Agency Tip" — practical guidance for agency-context work
- "Common Pitfall" — what teams actually get wrong
- "Before / After" — concrete example pairs

Do not introduce a fifth block type without a reason.

## Brand

- Ochre: #FF4900 (exact). Ink, paper, rule vars unchanged.
- Fonts unchanged: Syne (display), DM Sans (body), JetBrains Mono (labels).
- DEPT® logo URL: https://www.deptagency.com/wp-content/uploads/2025/10/logo-dept.svg
- Dark mode + per-page localStorage theme keys must keep working.

## Agent orchestration

Four subagents in this project:

- **c0** · Content builder. Edits content/source/ JSON files (the source of
  truth) and the rendered HTML in content/frozen/ when a re-render is
  needed. Also touches sample apps. Plans before building. Always.
- **content-quality** · Read-only reviewer. MUST be invoked after every
  c0 completion to verify brand, voice, structural integrity,
  accessibility, and AI-tell discipline.
- **q0** · Quiz curator. Drafts question-bank additions when c0
  introduces new sections or new architectural concepts. Read-only.
- **l0** · Skill / prompt-library builder. Generates reusable prompts
  for the team. Outputs land in prompts-library/.

### Workflow when the user asks for content changes

1. Dispatch c0. C0 plans first, awaits approval, then builds.
2. After c0 completes a module: ALWAYS invoke content-quality.
3. IF c0's edit introduced a new section, deepblock, or architectural
   concept: ALSO invoke q0.
4. Present both reports to the user before the next c0 turn.

### When NOT to invoke q0

Typo fixes, CSS tweaks, link updates, copy polish, image swaps, scan-box
additions to existing content. q0 is for new architectural concepts only.