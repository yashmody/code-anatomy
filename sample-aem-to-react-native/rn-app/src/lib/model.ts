// =================================================================
// model.ts · TypeScript shapes for AEM Content Fragments
// =================================================================
//
// These types are the typed wire format the app expects from AEM's
// persisted GraphQL queries. They mirror article-model.json field-by-field.
//
// Discipline:
//   - One type per CF model on the AEM side. No combined "view models" here.
//   - View-specific shapes live in components/, derived from these via
//     small transformer functions (see lib/transformers.ts).
//   - When the AEM model changes, this file changes first. Then the
//     screens and components are updated to match. Compilation tells you
//     where the changes propagate.
//
// This is the Stalwart "model.js" file in the React-Native flavour.

/** A DAM asset reference resolved by AEM to a published URL. */
export interface ImageRef {
  _publishUrl: string;
  width?: number;
  height?: number;
  mimeType?: string;
}

/** Author content fragment (nested via reference in Article). */
export interface Author {
  name: string;
  bio?: string;
  avatar?: ImageRef;
}

/** Article category — enum values from the CF model. */
export type ArticleCategory = "news" | "feature" | "review" | "interview";

/** Article — full shape returned by article-by-slug. */
export interface Article {
  _path: string;
  slug: string;
  title: string;
  summary: string;
  body?: string;        // rich text (raw)
  bodyHtml?: string;    // explicit HTML rendering
  category: ArticleCategory;
  publishDate: string;  // ISO datetime
  readTimeMin?: number;
  isFeatured?: boolean;
  hero?: ImageRef;
  author?: Author;
}

/** Lightweight article — shape returned by list-articles and featured-articles. */
export type ArticleSummary = Pick<
  Article,
  "_path" | "slug" | "title" | "summary" | "category" |
  "publishDate" | "readTimeMin" | "isFeatured" | "hero" | "author"
>;

/** AEM GraphQL response envelope. */
export interface ArticleListResponse<T = ArticleSummary> {
  data: {
    articleList: {
      items: T[];
    };
  };
}

/** Type guard — useful for narrowing in render code. */
export function isFullArticle(a: Article | ArticleSummary): a is Article {
  return "body" in a || "bodyHtml" in a;
}

/** Derived: "is this article new?" (under 7 days old). UI-side helper. */
export function isNew(publishDate: string, daysThreshold = 7): boolean {
  const published = new Date(publishDate).getTime();
  const now = Date.now();
  const days = (now - published) / (1000 * 60 * 60 * 24);
  return days <= daysThreshold;
}
