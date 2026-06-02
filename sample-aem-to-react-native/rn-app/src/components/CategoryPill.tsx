// CategoryPill.tsx · tag for category enum
import React from "react";
import { Text, StyleSheet } from "react-native";
import type { ArticleCategory } from "../lib/model";

const COLORS: Record<ArticleCategory, string> = {
  news: "#0a0a0a",
  feature: "#FF4900",
  review: "#22c55e",
  interview: "#3b82f6",
};

export function CategoryPill({ category }: { category: ArticleCategory }) {
  return (
    <Text style={[styles.pill, { color: COLORS[category], borderColor: COLORS[category] }]}>
      {category.toUpperCase()}
    </Text>
  );
}

const styles = StyleSheet.create({
  pill: {
    fontFamily: "JetBrainsMono-Bold",
    fontSize: 10,
    letterSpacing: 1.5,
    borderWidth: 1,
    paddingHorizontal: 6,
    paddingVertical: 2,
  },
});
