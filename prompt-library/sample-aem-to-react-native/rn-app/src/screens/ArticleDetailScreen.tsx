// =================================================================
// ArticleDetailScreen.tsx · full article body
// =================================================================
//
// Fetches one article by slug. Renders body as HTML in a WebView-like
// component (here represented as a Text fallback; in a real app, wire
// react-native-render-html).

import React, { useEffect, useState, useCallback } from "react";
import {
  ScrollView,
  View,
  Text,
  StyleSheet,
  Pressable,
  Dimensions,
} from "react-native";
import type { Article } from "../lib/model";
import { articleBySlug } from "../lib/api";
import { swr } from "../lib/cache";
import { HeroImage } from "../components/HeroImage";
import { AuthorChip } from "../components/AuthorChip";
import { CategoryPill } from "../components/CategoryPill";
import { LoadingState, ErrorState } from "../components/EmptyState";

interface Props {
  slug: string;
  onBack: () => void;
}

export function ArticleDetailScreen({ slug, onBack }: Props) {
  const [article, setArticle] = useState<Article | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    setError(null);
    swr<Article | null>(
      `article:${slug}`,
      () => articleBySlug(slug),
      ({ data, error }) => {
        if (data) setArticle(data);
        if (error && !data) setError(error.message);
        setLoading(false);
      }
    );
  }, [slug]);

  useEffect(() => {
    load();
  }, [load]);

  if (loading && !article) return <LoadingState label="Loading article…" />;
  if (error && !article) return <ErrorState message={error} onRetry={load} />;
  if (!article) return <ErrorState message="Article not found." />;

  const publishedFormatted = new Date(article.publishDate).toLocaleDateString(
    undefined,
    { year: "numeric", month: "long", day: "numeric" }
  );

  return (
    <ScrollView contentContainerStyle={styles.scroll}>
      <Pressable onPress={onBack} style={styles.backBtn} accessibilityRole="button">
        <Text style={styles.backTxt}>← BACK</Text>
      </Pressable>

      {article.hero && <HeroImage image={article.hero} aspectRatio={16 / 9} />}

      <View style={styles.body}>
        <View style={styles.metaRow}>
          <CategoryPill category={article.category} />
          <Text style={styles.dateTxt}>{publishedFormatted}</Text>
        </View>

        <Text style={styles.title}>{article.title}</Text>

        <Text style={styles.summary}>{article.summary}</Text>

        {article.author && (
          <View style={styles.authorRow}>
            <AuthorChip author={article.author} />
            {article.readTimeMin && (
              <Text style={styles.readTime}>{article.readTimeMin} MIN READ</Text>
            )}
          </View>
        )}

        <View style={styles.divider} />

        {/* In a production app, wire react-native-render-html here. */}
        <Text style={styles.bodyText}>
          {stripHtml(article.bodyHtml ?? article.body ?? "")}
        </Text>

        {article.author?.bio && (
          <View style={styles.bioBlock}>
            <Text style={styles.bioLabel}>ABOUT THE AUTHOR</Text>
            <Text style={styles.bioText}>{article.author.bio}</Text>
          </View>
        )}
      </View>
    </ScrollView>
  );
}

/** Minimal HTML strip — replace with a real renderer in production. */
function stripHtml(html: string): string {
  return html
    .replace(/<\/(p|div|li|h[1-6])>/gi, "\n\n")
    .replace(/<br\s*\/?>/gi, "\n")
    .replace(/<[^>]+>/g, "")
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

const { width } = Dimensions.get("window");

const styles = StyleSheet.create({
  scroll: { paddingBottom: 48 },
  backBtn: {
    paddingHorizontal: 16,
    paddingTop: 12,
    paddingBottom: 8,
  },
  backTxt: {
    fontFamily: "JetBrainsMono-Bold",
    fontSize: 11,
    letterSpacing: 1.5,
    color: "#FF4900",
  },
  body: { paddingHorizontal: 18, paddingTop: 20 },
  metaRow: { flexDirection: "row", alignItems: "center", gap: 10, marginBottom: 14 },
  dateTxt: {
    fontFamily: "JetBrainsMono-Regular",
    fontSize: 11,
    color: "#6f6f6f",
    letterSpacing: 0.8,
  },
  title: {
    fontFamily: "Syne-Bold",
    fontSize: 34,
    lineHeight: 38,
    color: "#0a0a0a",
    letterSpacing: -0.6,
    marginBottom: 14,
  },
  summary: {
    fontFamily: "DMSans-Bold",
    fontSize: 18,
    lineHeight: 26,
    color: "#3f3f3f",
    marginBottom: 18,
  },
  authorRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingVertical: 12,
    borderTopWidth: 1,
    borderTopColor: "#e6e3dc",
    borderBottomWidth: 1,
    borderBottomColor: "#e6e3dc",
  },
  readTime: {
    fontFamily: "JetBrainsMono-Bold",
    fontSize: 10,
    letterSpacing: 1.2,
    color: "#FF4900",
  },
  divider: { height: 24 },
  bodyText: {
    fontFamily: "DMSans-Regular",
    fontSize: 16,
    lineHeight: 26,
    color: "#0a0a0a",
  },
  bioBlock: {
    marginTop: 32,
    paddingTop: 18,
    borderTopWidth: 2,
    borderTopColor: "#0a0a0a",
  },
  bioLabel: {
    fontFamily: "JetBrainsMono-Bold",
    fontSize: 10,
    letterSpacing: 1.5,
    color: "#FF4900",
    marginBottom: 8,
  },
  bioText: {
    fontFamily: "DMSans-Regular",
    fontSize: 14,
    lineHeight: 22,
    color: "#3f3f3f",
  },
});
