// =================================================================
// CategoryScreen.tsx · filter view by category
// =================================================================

import React, { useEffect, useState, useCallback } from "react";
import {
  View,
  FlatList,
  Pressable,
  Text,
  StyleSheet,
  ScrollView,
  RefreshControl,
} from "react-native";
import type { ArticleCategory, ArticleSummary } from "../lib/model";
import { listArticles } from "../lib/api";
import { swr, invalidate } from "../lib/cache";
import { ArticleCard } from "../components/ArticleCard";
import { LoadingState, ErrorState, EmptyState } from "../components/EmptyState";

const ALL: ArticleCategory[] = ["news", "feature", "review", "interview"];

interface Props {
  onOpenArticle: (slug: string) => void;
  onBack: () => void;
}

export function CategoryScreen({ onOpenArticle, onBack }: Props) {
  const [active, setActive] = useState<ArticleCategory>("news");
  const [articles, setArticles] = useState<ArticleSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(
    (category: ArticleCategory) => {
      setLoading(true);
      setError(null);
      swr<ArticleSummary[]>(
        `articles:cat:${category}`,
        () => listArticles({ category, limit: 30 }),
        ({ data, error }) => {
          if (data) setArticles(data);
          else setArticles([]);
          if (error && !data) setError(error.message);
          setLoading(false);
        }
      );
    },
    []
  );

  useEffect(() => {
    load(active);
  }, [active, load]);

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    await invalidate(`articles:cat:${active}`);
    load(active);
    setRefreshing(false);
  }, [active, load]);

  return (
    <View style={{ flex: 1 }}>
      <View style={styles.header}>
        <Pressable onPress={onBack} accessibilityRole="button">
          <Text style={styles.backTxt}>← BACK</Text>
        </Pressable>
        <Text style={styles.title}>Browse</Text>
      </View>

      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        contentContainerStyle={styles.tabs}
      >
        {ALL.map((c) => (
          <Pressable
            key={c}
            onPress={() => setActive(c)}
            style={[styles.tab, active === c && styles.tabActive]}
          >
            <Text style={[styles.tabTxt, active === c && styles.tabTxtActive]}>
              {c.toUpperCase()}
            </Text>
          </Pressable>
        ))}
      </ScrollView>

      {loading && !articles.length ? (
        <LoadingState />
      ) : error && !articles.length ? (
        <ErrorState message={error} onRetry={() => load(active)} />
      ) : articles.length === 0 ? (
        <EmptyState label={`No ${active} articles yet.`} />
      ) : (
        <FlatList
          data={articles}
          keyExtractor={(item) => item._path}
          renderItem={({ item }) => <ArticleCard article={item} onPress={onOpenArticle} />}
          contentContainerStyle={styles.list}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor="#FF4900" />}
        />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  header: {
    paddingHorizontal: 16,
    paddingTop: 12,
    paddingBottom: 14,
    gap: 12,
    borderBottomWidth: 1,
    borderBottomColor: "#e6e3dc",
  },
  backTxt: {
    fontFamily: "JetBrainsMono-Bold",
    fontSize: 11,
    letterSpacing: 1.5,
    color: "#FF4900",
  },
  title: {
    fontFamily: "Syne-Bold",
    fontSize: 32,
    color: "#0a0a0a",
    letterSpacing: -0.6,
  },
  tabs: {
    paddingHorizontal: 16,
    paddingVertical: 14,
    gap: 8,
  },
  tab: {
    paddingHorizontal: 14,
    paddingVertical: 8,
    borderWidth: 1,
    borderColor: "#e6e3dc",
  },
  tabActive: {
    backgroundColor: "#FF4900",
    borderColor: "#FF4900",
  },
  tabTxt: {
    fontFamily: "JetBrainsMono-Bold",
    fontSize: 11,
    letterSpacing: 1.5,
    color: "#3f3f3f",
  },
  tabTxtActive: { color: "#fff" },
  list: { padding: 16, paddingBottom: 32 },
});
