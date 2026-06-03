// =================================================================
// HomeScreen.tsx · list of articles + featured rail
// =================================================================
//
// Composition only: fetch via api + cache, render via components.
// This file owns no rendering primitives and no data shapes — it wires
// existing pieces together.

import React, { useEffect, useState, useCallback } from "react";
import {
  View,
  FlatList,
  RefreshControl,
  StyleSheet,
  Text,
  ScrollView,
  Pressable,
  Image,
} from "react-native";
import type { ArticleSummary } from "../lib/model";
import { listArticles, featuredArticles } from "../lib/api";
import { swr, invalidate } from "../lib/cache";
import { ArticleCard } from "../components/ArticleCard";
import { LoadingState, ErrorState, EmptyState } from "../components/EmptyState";

interface Props {
  onOpenArticle: (slug: string) => void;
  onOpenCategory: () => void;
}

export function HomeScreen({ onOpenArticle, onOpenCategory }: Props) {
  const [articles, setArticles] = useState<ArticleSummary[]>([]);
  const [featured, setFeatured] = useState<ArticleSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(() => {
    setError(null);
    swr<ArticleSummary[]>(
      "articles:home",
      () => listArticles({ limit: 30 }),
      ({ data, error }) => {
        if (data) setArticles(data);
        if (error && !data) setError(error.message);
        setLoading(false);
      }
    );
    swr<ArticleSummary[]>(
      "articles:featured",
      () => featuredArticles(5),
      ({ data }) => {
        if (data) setFeatured(data);
      }
    );
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    await Promise.all([invalidate("articles:home"), invalidate("articles:featured")]);
    load();
    setRefreshing(false);
  }, [load]);

  if (loading && !articles.length) return <LoadingState label="Loading articles…" />;
  if (error && !articles.length) return <ErrorState message={error} onRetry={load} />;

  return (
    <FlatList
      data={articles}
      keyExtractor={(item) => item._path}
      renderItem={({ item }) => <ArticleCard article={item} onPress={onOpenArticle} />}
      contentContainerStyle={styles.list}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor="#FF4900" />}
      ListHeaderComponent={
        <>
          <View style={styles.headerRow}>
            <Text style={styles.title}>Latest</Text>
            <Pressable onPress={onOpenCategory} accessibilityRole="button">
              <Text style={styles.headerLink}>BROWSE BY CATEGORY →</Text>
            </Pressable>
          </View>

          {featured.length > 0 && (
            <>
              <Text style={styles.railLabel}>FEATURED</Text>
              <ScrollView
                horizontal
                showsHorizontalScrollIndicator={false}
                contentContainerStyle={styles.rail}
              >
                {featured.map((a) => (
                  <Pressable
                    key={a._path}
                    style={styles.featuredCard}
                    onPress={() => onOpenArticle(a.slug)}
                  >
                    {a.hero && (
                      <Image source={{ uri: a.hero._publishUrl }} style={styles.featuredImg} />
                    )}
                    <Text style={styles.featuredTitle} numberOfLines={2}>
                      {a.title}
                    </Text>
                  </Pressable>
                ))}
              </ScrollView>
              <Text style={styles.sectionLabel}>ALL ARTICLES</Text>
            </>
          )}
        </>
      }
      ListEmptyComponent={<EmptyState label="No articles yet." />}
    />
  );
}

const styles = StyleSheet.create({
  list: { padding: 16, paddingBottom: 32 },
  headerRow: {
    flexDirection: "row",
    alignItems: "baseline",
    justifyContent: "space-between",
    marginBottom: 20,
    marginTop: 8,
  },
  title: {
    fontFamily: "Syne-Bold",
    fontSize: 36,
    color: "#0a0a0a",
    letterSpacing: -0.8,
  },
  headerLink: {
    fontFamily: "JetBrainsMono-Bold",
    fontSize: 10,
    letterSpacing: 1.5,
    color: "#FF4900",
  },
  railLabel: {
    fontFamily: "JetBrainsMono-Bold",
    fontSize: 11,
    letterSpacing: 1.8,
    color: "#FF4900",
    marginBottom: 10,
  },
  rail: { gap: 12, paddingRight: 16, marginBottom: 28 },
  featuredCard: { width: 240 },
  featuredImg: {
    width: 240,
    height: 135,
    backgroundColor: "#f6f5f1",
    marginBottom: 8,
  },
  featuredTitle: {
    fontFamily: "Syne-Bold",
    fontSize: 16,
    lineHeight: 20,
    color: "#0a0a0a",
  },
  sectionLabel: {
    fontFamily: "JetBrainsMono-Bold",
    fontSize: 11,
    letterSpacing: 1.8,
    color: "#FF4900",
    marginBottom: 10,
  },
});
