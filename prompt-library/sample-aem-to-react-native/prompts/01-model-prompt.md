# 01 · Model Prompt

Generates `rn-app/src/lib/model.ts` from the AEM Content Fragment model
definition. This is the prompt that turns a JSON schema authors edited
in AEM into typed TypeScript a mobile app can rely on.

The reason this prompt is one of the highest-leverage in the project:
the model is the contract. Get the types right and every downstream
file gets simpler. Get the types wrong and every downstream file fights
the wrong shape.

---

## Prerequisite

Run prompt 00 first to establish the layering contract.

## The prompt

```
Read aem-side/article-model.json.

Generate rn-app/src/lib/model.ts following the LAYER 1 rules from the
architecture contract.

Requirements:
1. One TypeScript interface per CF model in the JSON (Article, Author).
   Use the exact field names from the JSON.
2. For DAM references (content-reference of type asset), define a
   shared ImageRef interface with _publishUrl, width, height, mimeType.
   AEM resolves DAM references to this shape via the persisted query.
3. For nested fragment references (content-reference of type fragment),
   inline the referenced type (Author is referenced inside Article).
4. For enumeration fields, define a string-literal union type.
5. Add a `Pick<>`-based summary type for the lighter shape returned by
   list-articles (no body, no bodyHtml).
6. Add a response envelope type matching AEM's GraphQL response shape:
   { data: { articleList: { items: T[] } } }
7. Add a type guard `isFullArticle()` distinguishing summary from full.
8. Add a UI helper `isNew(publishDate, daysThreshold)` returning whether
   the article is recent.

Output the file content only — no commentary. Include the file-header
comment described in LAYER 1.
```

## What this prompt teaches

It demonstrates that AEM → TypeScript can be a one-shot generation when
the CF model JSON is well-defined. The model.json IS the source of
truth; model.ts is generated artefact.

In a production setup, this prompt becomes a CI step: any change to
the CF model in AEM regenerates model.ts and triggers compile errors
in any screen that depends on a changed field. The schema enforces
itself.

## What to verify after generation

- [ ] Every field from the JSON is in the TypeScript
- [ ] Enum field is a union type, not a string
- [ ] Optional fields (no `required: true`) are marked `?:` in TypeScript
- [ ] `Pick<>` summary type lists the exact fields list-articles returns
- [ ] Type guard is correct (checks the discriminator: presence of `body`)
- [ ] No use of `any` anywhere

## Next prompt

Proceed to 02-api-prompt.md to generate the GraphQL client.
