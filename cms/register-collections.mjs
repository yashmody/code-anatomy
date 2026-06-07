#!/usr/bin/env node
// ============================================================================
// DEPT Anatomy of Code — Directus collection/role/permission/flow registrar.
// Phase 4a, Slice 4a-2. Source of truth for the parts a schema snapshot
// CANNOT capture cleanly across a fresh instance: registering collections
// over EXISTING tables, the staff roles, their permissions, and the
// cache-invalidation Flow.
//
// Idempotent: every create is guarded by a prior existence check, so re-runs
// are no-ops. Drives the Directus REST API with an admin token obtained by
// logging in as ADMIN_EMAIL/ADMIN_PASSWORD (from cms/.env).
//
// CRITICAL DESIGN POINT — "register over existing table, do NOT recreate":
//   * POST /collections with a body that has NO `schema` object tells Directus
//     to create only the *Directus metadata* (directus_collections row) and
//     bind it to the already-present Postgres table. It does NOT run CREATE
//     TABLE. We then POST /fields/:collection per existing column with
//     `schema: null` (meta-only) so Directus tracks the column without DDL.
//   * This is exactly the "introspect existing tables" requirement: Phase 4a
//     is additive and reversible. We never move content or alter the schema.
// ============================================================================

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));

// --- minimal .env loader (no dependency) -----------------------------------
function loadEnv() {
  const env = { ...process.env };
  try {
    const raw = readFileSync(join(__dirname, ".env"), "utf8");
    for (const line of raw.split("\n")) {
      const t = line.trim();
      if (!t || t.startsWith("#")) continue;
      const eq = t.indexOf("=");
      if (eq === -1) continue;
      const k = t.slice(0, eq).trim();
      const v = t.slice(eq + 1).trim();
      if (env[k] === undefined) env[k] = v;
    }
  } catch {
    /* .env optional if vars already exported */
  }
  return env;
}

const ENV = loadEnv();
const BASE = (ENV.PUBLIC_URL || "http://localhost:8055").replace(/\/$/, "");
const ADMIN_EMAIL = ENV.ADMIN_EMAIL || "admin@deptagency.com";
const ADMIN_PASSWORD = ENV.ADMIN_PASSWORD;
const WEBHOOK_URL =
  ENV.FASTAPI_WEBHOOK_URL || "http://127.0.0.1:8000/api/cms/webhook";

if (!ADMIN_PASSWORD) {
  console.error("ADMIN_PASSWORD not set (cms/.env). Cannot log in.");
  process.exit(1);
}

let TOKEN = null;

async function api(method, path, body) {
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers: {
      "Content-Type": "application/json",
      ...(TOKEN ? { Authorization: `Bearer ${TOKEN}` } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  const text = await res.text();
  let json = null;
  try {
    json = text ? JSON.parse(text) : null;
  } catch {
    json = { raw: text };
  }
  return { status: res.status, ok: res.ok, json };
}

async function login() {
  const r = await api("POST", "/auth/login", {
    email: ADMIN_EMAIL,
    password: ADMIN_PASSWORD,
  });
  if (!r.ok || !r.json?.data?.access_token) {
    throw new Error(`login failed (${r.status}): ${JSON.stringify(r.json)}`);
  }
  TOKEN = r.json.data.access_token;
  console.log(`  logged in as ${ADMIN_EMAIL}`);
}

// ============================================================================
// 1) COLLECTION MAP — collections bound to EXISTING tables.
//    `fields` lists existing columns with their Directus interface; primary
//    key marked. We never pass a `schema` object on create (meta-only bind).
//    Per the ACTUAL codecoder schema (verified live), not the idealised doc.
// ============================================================================
const COLLECTIONS = [
  {
    collection: "course_chapters",
    note: "The field manual — 31 chapters. PK is `filename`.",
    pk: "filename",
    icon: "menu_book",
    fields: [
      { field: "filename", type: "string", interface: "input", pk: true },
      { field: "ring", type: "string", interface: "input" },
      { field: "title", type: "string", interface: "input" },
      { field: "content", type: "json", interface: "input-code", options: { language: "json" } },
      { field: "created_at", type: "timestamp", interface: "datetime", readonly: true },
      { field: "updated_at", type: "timestamp", interface: "datetime", readonly: true },
    ],
  },
  {
    collection: "frameworks",
    note: "The spine — 2 rows (framework, explainer). PK is `id`.",
    pk: "id",
    icon: "account_tree",
    fields: [
      { field: "id", type: "string", interface: "input", pk: true },
      { field: "data", type: "json", interface: "input-code", options: { language: "json" } },
      { field: "updated_at", type: "timestamp", interface: "datetime", readonly: true },
    ],
  },
  {
    collection: "questions",
    note: "Quiz bank (official + UGC). PK is `id`.",
    pk: "id",
    icon: "quiz",
    fields: [
      { field: "id", type: "string", interface: "input", pk: true },
      { field: "topic", type: "string", interface: "input" },
      { field: "difficulty", type: "string", interface: "select-dropdown",
        options: { choices: [{ text: "easy", value: "easy" }, { text: "medium", value: "medium" }, { text: "hard", value: "hard" }] } },
      { field: "question", type: "text", interface: "input-multiline" },
      { field: "options", type: "json", interface: "input-code", options: { language: "json" } },
      { field: "correct_index", type: "integer", interface: "input" },
      { field: "explanation", type: "text", interface: "input-multiline" },
      { field: "status", type: "string", interface: "select-dropdown",
        options: { choices: [{ text: "draft", value: "draft" }, { text: "pending_review", value: "pending_review" }, { text: "published", value: "published" }] } },
      { field: "version", type: "integer", interface: "input" },
      { field: "author_id", type: "string", interface: "input" },
      { field: "is_user_submitted", type: "boolean", interface: "boolean" },
      { field: "created_at", type: "timestamp", interface: "datetime", readonly: true },
      { field: "updated_at", type: "timestamp", interface: "datetime", readonly: true },
    ],
  },
  {
    collection: "feed_items",
    note: "UGC + moderation surface. PK is `id`. `search` is a generated tsvector — read-only.",
    pk: "id",
    icon: "dynamic_feed",
    fields: [
      { field: "id", type: "string", interface: "input", pk: true },
      { field: "type", type: "string", interface: "select-dropdown",
        options: { choices: [{ text: "post", value: "post" }, { text: "video", value: "video" }, { text: "list", value: "list" }, { text: "card", value: "card" }, { text: "vocab", value: "vocab" }, { text: "scenario", value: "scenario" }] } },
      { field: "status", type: "string", interface: "select-dropdown",
        options: { choices: [{ text: "pending_review", value: "pending_review" }, { text: "published", value: "published" }, { text: "flagged", value: "flagged" }, { text: "removed", value: "removed" }] } },
      { field: "author_id", type: "string", interface: "input" },
      { field: "framework_ref", type: "string", interface: "input" },
      { field: "topics", type: "csv", interface: "tags" },
      { field: "created_at", type: "timestamp", interface: "datetime", readonly: true },
      { field: "updated_at", type: "timestamp", interface: "datetime", readonly: true },
      { field: "data", type: "json", interface: "input-code", options: { language: "json" } },
      // search is a generated tsvector column — register read-only so editors
      // never attempt to write it (Postgres would reject a write anyway).
      { field: "search", type: "text", interface: "input", readonly: true },
    ],
  },
  {
    collection: "app_config",
    note: "Config-as-content. PK is `key`. platform_admin only.",
    pk: "key",
    icon: "tune",
    fields: [
      { field: "key", type: "string", interface: "input", pk: true },
      { field: "value", type: "json", interface: "input-code", options: { language: "json" } },
      { field: "value_type", type: "string", interface: "select-dropdown",
        options: { choices: [{ text: "string", value: "string" }, { text: "int", value: "int" }, { text: "float", value: "float" }, { text: "bool", value: "bool" }, { text: "json", value: "json" }] } },
      { field: "description", type: "text", interface: "input-multiline" },
      { field: "updated_at", type: "timestamp", interface: "datetime", readonly: true },
    ],
  },
  {
    collection: "media_assets",
    note: "Metadata only — Directus never rewrites the bytes (large_object_oid is read-only).",
    pk: "id",
    icon: "perm_media",
    fields: [
      { field: "id", type: "string", interface: "input", pk: true },
      { field: "large_object_oid", type: "integer", interface: "input", readonly: true },
      { field: "filename", type: "string", interface: "input" },
      { field: "mime_type", type: "string", interface: "input" },
      { field: "size_bytes", type: "bigInteger", interface: "input", readonly: true },
      { field: "uploaded_by", type: "string", interface: "input" },
      { field: "uploaded_at", type: "timestamp", interface: "datetime", readonly: true },
    ],
  },
  {
    collection: "users",
    note: "Read-only reference (author picker). PK is `email`.",
    pk: "email",
    icon: "person",
    readOnlyCollection: true,
    fields: [
      { field: "email", type: "string", interface: "input", pk: true },
      { field: "name", type: "string", interface: "input" },
      { field: "role", type: "string", interface: "input" },
      { field: "provider", type: "string", interface: "input" },
      { field: "persona", type: "string", interface: "input" },
    ],
  },
  {
    collection: "roles",
    note: "Read-only reference. PK is `id` (surrogate).",
    pk: "id",
    icon: "badge",
    readOnlyCollection: true,
    fields: [
      { field: "id", type: "integer", interface: "input", pk: true },
      { field: "key", type: "string", interface: "input" },
      { field: "plane", type: "string", interface: "input" },
      { field: "description", type: "text", interface: "input-multiline" },
    ],
  },
  {
    collection: "user_roles",
    note: "Read-only — composite PK; grants are issued via the FastAPI admin endpoint (05 §3.7).",
    pk: "user_email",
    icon: "key",
    readOnlyCollection: true,
    // Directus IGNORES this collection at introspection time because it has a
    // composite PK and no single primary key column (05 §3.7 predicted this).
    // Skip field registration — there is no Directus-trackable collection to
    // attach fields to. Grants stay read-only-via-FastAPI by design.
    skipFields: true,
    fields: [
      { field: "user_email", type: "string", interface: "input", pk: true },
      { field: "role_id", type: "integer", interface: "input" },
      { field: "granted_at", type: "timestamp", interface: "datetime", readonly: true },
      { field: "granted_by", type: "string", interface: "input" },
    ],
  },
  // FAQs + runbooks are STATIC content under resources/ now (not Directus-managed);
  // their collections/tables were removed pre-cutover. See docs/CONTENT-AUTHORING.md.
];

async function getCollection(name) {
  const r = await api("GET", `/collections/${name}`);
  return r.status === 200 ? r.json.data : null;
}

function collectionMeta(c) {
  return { icon: c.icon || "box", note: c.note || null, hidden: false, singleton: false };
}

function fieldMeta(f) {
  return {
    interface: f.interface || "input",
    ...(f.options ? { options: f.options } : {}),
    ...(f.readonly ? { readonly: true } : {}),
    hidden: false,
  };
}

async function registerCollections() {
  for (const c of COLLECTIONS) {
    const existing = await getCollection(c.collection);
    if (!existing) {
      // meta-only create: NO `schema` key => bind to existing table, no DDL.
      const r = await api("POST", "/collections", {
        collection: c.collection,
        meta: collectionMeta(c),
      });
      if (!r.ok) {
        console.error(`  [collection] FAILED create ${c.collection} (${r.status}): ${JSON.stringify(r.json)}`);
        continue;
      }
      console.log(`  [collection] ${c.collection} registered (bound to existing table, no DDL)`);
    } else if (existing.meta == null) {
      // Auto-introspected collection with NO Directus metadata. Attach meta so
      // (a) the interfaces/notes apply and (b) `schema snapshot` captures it.
      const r = await api("PATCH", `/collections/${c.collection}`, { meta: collectionMeta(c) });
      if (!r.ok) {
        console.error(`  [collection] FAILED meta ${c.collection} (${r.status}): ${JSON.stringify(r.json)}`);
      } else {
        console.log(`  [collection] ${c.collection} meta attached (was introspected) — now in snapshot`);
      }
    } else {
      console.log(`  [collection] ${c.collection} already has meta — skip`);
    }

    // Composite-PK collections (user_roles) are ignored by Directus
    // introspection — there is no collection to attach fields to. Skip.
    if (c.skipFields) {
      console.log(`    [fields] ${c.collection} skipped (composite PK; read-only via FastAPI)`);
      continue;
    }

    // Attach/refresh each field's Directus metadata. The column already exists
    // (introspected); we PATCH meta only (schema: null) so we never run DDL but
    // the interface/options are applied AND the field is captured by snapshot.
    for (const f of c.fields) {
      const fr = await api("GET", `/fields/${c.collection}/${f.field}`);
      if (fr.status !== 200) {
        // Field not introspected (rare) — create meta-only.
        const cr = await api("POST", `/fields/${c.collection}`, {
          field: f.field, type: f.type, schema: null, meta: fieldMeta(f),
        });
        console.log(cr.ok ? `    [field +] ${c.collection}.${f.field}` :
          `    [field] FAILED create ${c.collection}.${f.field} (${cr.status})`);
        continue;
      }
      // Introspected column present — attach meta (idempotent PATCH).
      const pr = await api("PATCH", `/fields/${c.collection}/${f.field}`, {
        meta: fieldMeta(f),
      });
      if (!pr.ok) {
        console.error(`    [field] FAILED meta ${c.collection}.${f.field} (${pr.status}): ${JSON.stringify(pr.json)}`);
      } else {
        console.log(`    [field ~] ${c.collection}.${f.field} (meta)`);
      }
    }
  }
}

// ============================================================================
// 2) STAFF ROLES — match the staff plane (04 §2.1). platform_admin is the
//    only role with admin_access; the other three are scoped via permissions.
// ============================================================================
const ROLES = [
  { name: "content_author", admin: false, app: true,
    description: "Create/edit course chapters, frameworks. CRUD own-draft on course_chapters; read media metadata." },
  { name: "quiz_admin", admin: false, app: true,
    description: "Create/update questions, approve UGC questions. CRUD questions; read content." },
  { name: "feed_moderator", admin: false, app: true,
    description: "Approve/flag/remove feed items. Update feed_items.status; read content." },
  { name: "platform_admin", admin: true, app: true,
    description: "Superuser across both planes. Full Directus admin; app_config R/W." },
];

const roleIds = {};

async function findRoleByName(name) {
  const r = await api("GET", `/roles?filter[name][_eq]=${encodeURIComponent(name)}&limit=1`);
  if (r.ok && r.json?.data?.length) return r.json.data[0];
  return null;
}

async function ensureRoles() {
  for (const role of ROLES) {
    const existing = await findRoleByName(role.name);
    if (existing) {
      roleIds[role.name] = existing.id;
      console.log(`  [role] ${role.name} exists (${existing.id})`);
      continue;
    }
    const r = await api("POST", "/roles", {
      name: role.name,
      admin_access: role.admin,
      app_access: role.app,
      description: role.description,
    });
    if (!r.ok) {
      console.error(`  [role] FAILED ${role.name} (${r.status}): ${JSON.stringify(r.json)}`);
      continue;
    }
    roleIds[role.name] = r.json.data.id;
    console.log(`  [role] ${role.name} created (${r.json.data.id})`);
  }
}

// ============================================================================
// 3a) ACCESS POLICIES (Directus 11 RBAC) — in Directus 11 permissions attach
//     to a POLICY, and a policy is linked to a role through the `access`
//     junction. We create one policy per scoped role and link it. The
//     platform_admin role has admin_access=true and needs no policy/perms.
// ============================================================================
const policyIds = {};

async function findPolicyByName(name) {
  const r = await api("GET", `/policies?filter[name][_eq]=${encodeURIComponent(name)}&limit=1`);
  if (r.ok && r.json?.data?.length) return r.json.data[0];
  return null;
}

async function accessLinkExists(roleId, policyId) {
  const r = await api(
    "GET",
    `/access?filter[role][_eq]=${roleId}&filter[policy][_eq]=${policyId}&limit=1`
  );
  return r.ok && r.json?.data?.length > 0;
}

async function ensurePolicies() {
  // Only the three scoped roles need a policy; platform_admin bypasses.
  for (const roleName of ["content_author", "quiz_admin", "feed_moderator"]) {
    const roleId = roleIds[roleName];
    if (!roleId) {
      console.error(`  [policy] no role id for ${roleName} — skip`);
      continue;
    }
    const policyName = `${roleName}-policy`;
    let policy = await findPolicyByName(policyName);
    if (policy) {
      policyIds[roleName] = policy.id;
      console.log(`  [policy] ${policyName} exists (${policy.id})`);
    } else {
      const r = await api("POST", "/policies", {
        name: policyName,
        description: `Permissions for the ${roleName} staff role (05 §3).`,
        app_access: true,
        admin_access: false,
        enforce_tfa: false,
      });
      if (!r.ok) {
        console.error(`  [policy] FAILED ${policyName} (${r.status}): ${JSON.stringify(r.json)}`);
        continue;
      }
      policyIds[roleName] = r.json.data.id;
      console.log(`  [policy] ${policyName} created (${r.json.data.id})`);
    }
    // Link role -> policy via the access junction.
    const policyId = policyIds[roleName];
    if (policyId && !(await accessLinkExists(roleId, policyId))) {
      const ar = await api("POST", "/access", { role: roleId, policy: policyId });
      if (!ar.ok) {
        console.error(`  [access] FAILED link ${roleName} (${ar.status}): ${JSON.stringify(ar.json)}`);
      } else {
        console.log(`  [access] linked ${roleName} -> ${policyName}`);
      }
    }
  }
}

// ============================================================================
// 3b) PERMISSIONS — per 05 §3 tables (cross-ref 04 §3). platform_admin needs
//    NO explicit permissions (admin_access=true bypasses). The three scoped
//    roles get explicit row rules attached to their POLICY. media_assets read
//    for all three. app_config is platform_admin-only => no scoped-role rule.
// ============================================================================
// Each entry: { role, collection, action, fields, permissions(filter) }
function permsFor() {
  return [
    // content_author — course_chapters CRU (no delete); frameworks CRU; read content; read media meta.
    { role: "content_author", collection: "course_chapters", action: "read", fields: ["*"] },
    { role: "content_author", collection: "course_chapters", action: "create", fields: ["*"] },
    { role: "content_author", collection: "course_chapters", action: "update", fields: ["*"] },
    { role: "content_author", collection: "frameworks", action: "read", fields: ["*"] },
    { role: "content_author", collection: "frameworks", action: "create", fields: ["*"] },
    { role: "content_author", collection: "frameworks", action: "update", fields: ["*"] },
    { role: "content_author", collection: "questions", action: "read", fields: ["*"] },
    { role: "content_author", collection: "feed_items", action: "read", fields: ["*"] },
    { role: "content_author", collection: "media_assets", action: "read", fields: ["*"] },
    { role: "content_author", collection: "users", action: "read", fields: ["email", "name", "role"] },

    // quiz_admin — questions CRU; read course/feed/frameworks; read media meta.
    { role: "quiz_admin", collection: "questions", action: "read", fields: ["*"] },
    { role: "quiz_admin", collection: "questions", action: "create", fields: ["*"] },
    { role: "quiz_admin", collection: "questions", action: "update", fields: ["*"] },
    { role: "quiz_admin", collection: "course_chapters", action: "read", fields: ["*"] },
    { role: "quiz_admin", collection: "frameworks", action: "read", fields: ["*"] },
    { role: "quiz_admin", collection: "feed_items", action: "read", fields: ["*"] },
    { role: "quiz_admin", collection: "media_assets", action: "read", fields: ["*"] },
    { role: "quiz_admin", collection: "users", action: "read", fields: ["email", "name", "role"] },

    // feed_moderator — read feed; update feed_items.status only; read content; read media meta.
    { role: "feed_moderator", collection: "feed_items", action: "read", fields: ["*"] },
    { role: "feed_moderator", collection: "feed_items", action: "update", fields: ["status"] },
    { role: "feed_moderator", collection: "questions", action: "read", fields: ["*"] },
    { role: "feed_moderator", collection: "questions", action: "update", fields: ["status"] },
    { role: "feed_moderator", collection: "course_chapters", action: "read", fields: ["*"] },
    { role: "feed_moderator", collection: "frameworks", action: "read", fields: ["*"] },
    { role: "feed_moderator", collection: "media_assets", action: "read", fields: ["*"] },
    { role: "feed_moderator", collection: "users", action: "read", fields: ["email", "name", "role"] },
  ];
}

async function permissionExists(policyId, collection, action) {
  const r = await api(
    "GET",
    `/permissions?filter[policy][_eq]=${policyId}&filter[collection][_eq]=${collection}&filter[action][_eq]=${action}&limit=1`
  );
  return r.ok && r.json?.data?.length > 0;
}

async function ensurePermissions() {
  for (const p of permsFor()) {
    const policyId = policyIds[p.role];
    if (!policyId) {
      console.error(`  [perm] no policy id for ${p.role} — skip`);
      continue;
    }
    if (await permissionExists(policyId, p.collection, p.action)) {
      console.log(`  [perm] ${p.role} ${p.action} ${p.collection} exists — skip`);
      continue;
    }
    const body = {
      policy: policyId,
      collection: p.collection,
      action: p.action,
      fields: p.fields || ["*"],
      permissions: p.permissions || {},
      validation: {},
    };
    const r = await api("POST", "/permissions", body);
    if (!r.ok) {
      console.error(`  [perm] FAILED ${p.role} ${p.action} ${p.collection} (${r.status}): ${JSON.stringify(r.json)}`);
    } else {
      console.log(`  [perm] ${p.role} ${p.action} ${p.collection} [${(p.fields || ["*"]).join(",")}]`);
    }
  }
}

// ============================================================================
// 4) CACHE-INVALIDATION FLOW — triggers on items.create/update/delete for the
//    five cached collections, fires a Webhook (Request URL) operation to the
//    FastAPI loopback receiver with body { collection, keys } (the shape
//    backend/app/modules/cms/routes.py accepts — "Directus standard").
// ============================================================================
const FLOW_NAME = "cache-invalidation";
const CACHED_COLLECTIONS = [
  "course_chapters",
  "frameworks",
  "questions",
  "feed_items",
  "app_config",
];

// Request-operation options. body is a JSON OBJECT (see note inside) — never
// a stringified JSON, or FastAPI's request.json() yields a str.
function requestOpOptions() {
  return {
    url: WEBHOOK_URL,
    method: "POST",
    headers: [{ header: "Content-Type", value: "application/json" }],
    // body MUST be a JSON OBJECT, not a stringified JSON. Directus's request
    // operation passes `body` straight to axios `data`; a string body is sent
    // as a quoted JSON scalar, so FastAPI's request.json() yields a str (the
    // "'str' object has no attribute 'get'" failure). An object lets Directus
    // resolve the {{$trigger.*}} templates and axios serialise a real JSON
    // object. {{$trigger.keys}} resolves to the array of primary keys touched.
    body: {
      collection: "{{$trigger.collection}}",
      keys: "{{$trigger.keys}}",
    },
  };
}

async function findFlowByName(name) {
  const r = await api(
    "GET",
    `/flows?filter[name][_eq]=${encodeURIComponent(name)}&limit=1&fields=id,name,operation,operations.id,operations.key,operations.options`
  );
  if (r.ok && r.json?.data?.length) return r.json.data[0];
  return null;
}

async function ensureFlow() {
  const existing = await findFlowByName(FLOW_NAME);
  if (existing) {
    // Self-heal: reconcile the existing operation's body so a re-run fixes an
    // older stringified-body operation (idempotent).
    const op = (existing.operations || []).find((o) => o.key === "post_to_fastapi") ||
      (existing.operations || [])[0];
    if (op) {
      const pr = await api("PATCH", `/operations/${op.id}`, { options: requestOpOptions() });
      if (pr.ok) {
        console.log(`  [flow] ${FLOW_NAME} exists (${existing.id}) — operation body reconciled (object body)`);
      } else {
        console.log(`  [flow] ${FLOW_NAME} exists (${existing.id}) — operation reconcile WARN (${pr.status})`);
      }
    } else {
      console.log(`  [flow] ${FLOW_NAME} exists (${existing.id}) — no operation found to reconcile`);
    }
    return;
  }
  // Create the flow with an action (non-blocking) trigger on the five
  // collections, all three row events.
  const flowBody = {
    name: FLOW_NAME,
    icon: "cached",
    color: "#FF4900",
    status: "active",
    trigger: "event",
    accountability: "all",
    options: {
      type: "action", // fires AFTER the DB write (non-blocking)
      scope: ["items.create", "items.update", "items.delete"],
      collections: CACHED_COLLECTIONS,
    },
  };
  const fr = await api("POST", "/flows", flowBody);
  if (!fr.ok) {
    console.error(`  [flow] FAILED create (${fr.status}): ${JSON.stringify(fr.json)}`);
    return;
  }
  const flowId = fr.json.data.id;
  console.log(`  [flow] ${FLOW_NAME} created (${flowId})`);

  // Webhook operation: POST { collection, keys } to the FastAPI loopback URL.
  // {{$trigger.collection}} and {{$trigger.keys}} are resolved by Directus at
  // run time. keys is the array of primary keys touched by the event.
  const opBody = {
    flow: flowId,
    name: "post-to-fastapi",
    key: "post_to_fastapi",
    type: "request",
    position_x: 19,
    position_y: 1,
    options: requestOpOptions(),
  };
  const or = await api("POST", "/operations", opBody);
  if (!or.ok) {
    console.error(`  [flow] FAILED operation (${or.status}): ${JSON.stringify(or.json)}`);
    return;
  }
  const opId = or.json.data.id;
  console.log(`  [flow] operation post-to-fastapi created (${opId}) -> ${WEBHOOK_URL}`);

  // Wire the flow's entrypoint to the operation.
  const wire = await api("PATCH", `/flows/${flowId}`, { operation: opId });
  if (!wire.ok) {
    console.error(`  [flow] FAILED wiring operation (${wire.status}): ${JSON.stringify(wire.json)}`);
  } else {
    console.log(`  [flow] wired entrypoint -> post-to-fastapi`);
  }
}

// ============================================================================
// 5) MODULE BAR — enable the custom `media-upload` module (full-page admin
//    screen, extensions/directus-extension-media-upload). A registered module
//    only appears in the bar once it is listed in `directus_settings.module_bar`;
//    a custom (non-core) module is never shown by the null-default. We append
//    our entry idempotently, preserving whatever is already there.
//
//    When `module_bar` is still null (fresh instance — the column is nullable
//    and not migration-seeded), the app renders the core defaults implicitly,
//    so we seed those defaults FIRST and then append ours. This mirrors exactly
//    what toggling the module on in Settings -> Modules would persist, so no
//    built-in module is hidden.
// ============================================================================
const MODULE_ID = "media-upload";

// Directus 11 core module bar default order (what a null `module_bar` renders).
// `settings` is included because the UI persists it when the bar is customised.
const DEFAULT_MODULE_BAR = [
  { type: "module", id: "content", enabled: true },
  { type: "module", id: "users", enabled: true },
  { type: "module", id: "files", enabled: true },
  { type: "module", id: "insights", enabled: true },
  { type: "module", id: "settings", enabled: true },
];

async function ensureModuleEnabled() {
  const r = await api("GET", "/settings?fields=module_bar");
  if (!r.ok) {
    console.error(`  [module] FAILED reading settings (${r.status}): ${JSON.stringify(r.json)}`);
    return;
  }
  const current = r.json?.data?.module_bar;
  let bar = Array.isArray(current) && current.length ? [...current] : null;

  if (!bar) {
    // Fresh instance — seed the core defaults so none get hidden, then add ours.
    bar = [...DEFAULT_MODULE_BAR];
    console.log("  [module] module_bar was empty — seeding core defaults before adding media-upload");
  }

  if (bar.some((e) => e && e.id === MODULE_ID)) {
    console.log(`  [module] ${MODULE_ID} already in module_bar — skip`);
    return;
  }

  bar.push({ type: "module", enabled: true, id: MODULE_ID });
  const pr = await api("PATCH", "/settings", { module_bar: bar });
  if (!pr.ok) {
    console.error(`  [module] FAILED enabling ${MODULE_ID} (${pr.status}): ${JSON.stringify(pr.json)}`);
  } else {
    console.log(`  [module] ${MODULE_ID} added to module_bar (full-page admin screen enabled)`);
  }
}

// ============================================================================
// MAIN
// ============================================================================
async function main() {
  console.log(`Directus registrar -> ${BASE}`);
  await login();
  console.log("\n== collections (bind over existing tables) ==");
  await registerCollections();
  console.log("\n== roles ==");
  await ensureRoles();
  console.log("\n== access policies (Directus 11 RBAC) ==");
  await ensurePolicies();
  console.log("\n== permissions ==");
  await ensurePermissions();
  console.log("\n== cache-invalidation flow ==");
  await ensureFlow();
  console.log("\n== module bar (media-upload screen) ==");
  await ensureModuleEnabled();

  console.log("\nDONE. Role ids (paste content_author into AUTH_GOOGLE_DEFAULT_ROLE_ID):");
  for (const [k, v] of Object.entries(roleIds)) console.log(`  ${k} = ${v}`);
}

main().catch((e) => {
  console.error("registrar FAILED:", e.message);
  process.exit(1);
});
