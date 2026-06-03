// =================================================================
// api.ts · AEM persisted GraphQL client
// =================================================================
//
// Calls AEM's persisted query endpoints. The app never sends a query
// body — only the persisted query path and parameters. This is what
// makes the wire shape stable and the CDN cache predictable.
//
// Discipline:
//   - One function per persisted query. No generic .query() escape hatch.
//   - Errors thrown — callers wrap in try/catch and translate to UI state.
//   - Network details (base URL, auth headers) injected via config, not
//     hardcoded.
//
// This is the Stalwart "api.js" file. It's the only file that knows
// HTTP exists.

import type {
  Article,
  ArticleCategory,
  ArticleListResponse,
  ArticleSummary,
} from "./model";

// -----------------------------------------------------------------
// Configuration — injected at app startup from app.config.ts
// -----------------------------------------------------------------
export interface AemClientConfig {
  /** e.g. "https://publish-p123-e456.adobeaemcloud.com" */
  baseUrl: string;
  /** AEM project namespace — matches the path under /conf/.../graphql/persistentQueries/ */
  namespace: string;
  /** Optional auth header value (e.g. "Bearer ..." for protected endpoints) */
  authToken?: string;
  /** Network timeout in ms */
  timeoutMs?: number;
}

let _config: AemClientConfig | null = null;

export function configureClient(cfg: AemClientConfig): void {
  _config = { timeoutMs: 8000, ...cfg };
}

function getConfig(): AemClientConfig {
  if (!_config) throw new Error("AEM client not configured — call configureClient() first");
  return _config;
}

// -----------------------------------------------------------------
// Internal: fetch a persisted query
// -----------------------------------------------------------------
async function fetchPersisted<T>(
  queryName: string,
  variables: Record<string, unknown> = {}
): Promise<T> {
  const cfg = getConfig();
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(variables)) {
    if (v !== undefined && v !== null) params.set(k, String(v));
  }

  const url = `${cfg.baseUrl}/graphql/execute.json/${cfg.namespace}/${queryName}${
    params.toString() ? "?" + params.toString() : ""
  }`;

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), cfg.timeoutMs ?? 8000);

  try {
    const res = await fetch(url, {
      method: "GET",
      headers: {
        Accept: "application/json",
        ...(cfg.authToken ? { Authorization: cfg.authToken } : {}),
      },
      signal: controller.signal,
    });

    if (!res.ok) {
      throw new ApiError(`AEM query "${queryName}" failed: HTTP ${res.status}`, res.status);
    }

    const json = (await res.json()) as ArticleListResponse<T>;
    return json as unknown as T;
  } catch (err) {
    if (err instanceof Error && err.name === "AbortError") {
      throw new ApiError(`AEM query "${queryName}" timed out`, 0);
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

export class ApiError extends Error {
  constructor(message: string, public status: number) {
    super(message);
    this.name = "ApiError";
  }
}

// -----------------------------------------------------------------
// Public API — one function per persisted query
// -----------------------------------------------------------------

export async function listArticles(opts: {
  category?: ArticleCategory;
  limit?: number;
  offset?: number;
} = {}): Promise<ArticleSummary[]> {
  const resp = await fetchPersisted<ArticleListResponse>("list-articles", {
    category: opts.category,
    limit: opts.limit ?? 20,
    offset: opts.offset ?? 0,
  });
  return resp.data.articleList.items;
}

export async function featuredArticles(limit = 5): Promise<ArticleSummary[]> {
  const resp = await fetchPersisted<ArticleListResponse>("featured-articles", { limit });
  return resp.data.articleList.items;
}

export async function articleBySlug(slug: string): Promise<Article | null> {
  if (!slug) throw new ApiError("slug is required", 400);
  const resp = await fetchPersisted<ArticleListResponse<Article>>("article-by-slug", { slug });
  return resp.data.articleList.items[0] ?? null;
}
