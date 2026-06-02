// =================================================================
// ArticleCard.tsx · row primitive for list views
// =================================================================
//
// Renders a single ArticleSummary in list form. No data fetching here;
// no navigation logic here. Receives the article and an onPress handler.
//
// This is the Stalwart "render" file flavour — purely presentational.

import React from "react";
import { Pressable, View, Text, StyleSheet } from "react-native";
import type { ArticleSummary } from "../lib/model";
import { isNew } from "../lib/model";
import { HeroImage } from "./HeroImage";
import { AuthorChip } from "./AuthorChip";
import { CategoryPill } from "./CategoryPill";

interface Props {
  article: ArticleSummary;
  onPress: (slug: string) => void;
}

export function ArticleCard({ article, onPress }: Props) {
  return (
    <Pressable
      onPress={() => onPress(article.slug)}
      style={({ pressed }) => [styles.card, pressed && styles.pressed]}
      accessibilityRole="button"
      accessibilityLabel={`Open article: ${article.title}`}
    >
      {article.hero && <HeroImage image={article.hero} aspectRatio={16 / 9} />}

      <View style={styles.body}>
        <View style={styles.metaRow}>
          <CategoryPill category={article.category} />
          {isNew(article.publishDate) && <Text style={styles.newBadge}>NEW</Text>}
        </View>

        <Text style={styles.title} numberOfLines={2}>
          {article.title}
        </Text>

        <Text style={styles.summary} numberOfLines={3}>
          {article.summary}
        </Text>

        <View style={styles.footer}>
          {article.author && <AuthorChip author={article.author} />}
          {article.readTimeMin && (
            <Text style={styles.readTime}>{article.readTimeMin} min read</Text>
          )}
        </View>
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: "#fff",
    borderRadius: 0,
    borderWidth: 1,
    borderColor: "#e6e3dc",
    borderLeftWidth: 4,
    borderLeftColor: "#FF4900",
    marginBottom: 14,
    overflow: "hidden",
  },
  pressed: {
    opacity: 0.85,
  },
  body: {
    padding: 16,
  },
  metaRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    marginBottom: 10,
  },
  newBadge: {
    fontFamily: "JetBrainsMono-Bold",
    fontSize: 10,
    letterSpacing: 1.5,
    color: "#FF4900",
    borderWidth: 1,
    borderColor: "#FF4900",
    paddingHorizontal: 6,
    paddingVertical: 2,
  },
  title: {
    fontFamily: "Syne-Bold",
    fontSize: 20,
    lineHeight: 24,
    color: "#0a0a0a",
    marginBottom: 6,
  },
  summary: {
    fontFamily: "DMSans-Regular",
    fontSize: 14,
    lineHeight: 20,
    color: "#3f3f3f",
    marginBottom: 12,
  },
  footer: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingTop: 10,
    borderTopWidth: 1,
    borderTopColor: "#e6e3dc",
  },
  readTime: {
    fontFamily: "JetBrainsMono-Regular",
    fontSize: 11,
    color: "#6f6f6f",
    letterSpacing: 0.5,
  },
});
