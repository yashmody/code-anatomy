# 04 · Screens & Components Prompts

Generates `rn-app/src/components/*.tsx` and `rn-app/src/screens/*.tsx`.
Three sub-prompts run in order. Each builds on the previous artefacts;
the layering contract from prompt 00 keeps each prompt focused.

---

## 04a · Component prompt

```
Generate the presentational components in rn-app/src/components/.
Each is a small, prop-driven React Native component. LAYER 4 rules:
no fetching, no AsyncStorage, no navigation.

Read rn-app/src/lib/model.ts for types.

Components to generate:

1. ArticleCard.tsx
   Props: article: ArticleSummary, onPress: (slug: string) => void.
   Renders: hero image (if present), category pill, NEW badge if
   isNew(publishDate), title (2 lines), summary (3 lines), author
   chip + read time in footer.

2. HeroImage.tsx
   Props: image: ImageRef, aspectRatio?: number (default 16/9).
   Reserves aspect-ratio space using image.width/height when present
   (to avoid CLS) and falls back to the prop.

3. AuthorChip.tsx
   Props: author: Author.
   Avatar (22px circle) + name in a single row.

4. CategoryPill.tsx
   Props: category: ArticleCategory.
   Colour-coded by category. Use:
     news → black, feature → ochre (#FF4900),
     review → green (#22c55e), interview → blue (#3b82f6).

5. EmptyState.tsx (file exports three components)
   - LoadingState (ActivityIndicator + label)
   - EmptyState (label)
   - ErrorState (message + optional onRetry callback)

Brand:
- Primary ochre: #FF4900
- Ink: #0a0a0a
- Paper: #ffffff
- Rule: #e6e3dc
- Fonts: Syne (display, bold), DM Sans (body), JetBrains Mono (labels).
  Use the family names "Syne-Bold", "DMSans-Regular", "DMSans-Bold",
  "JetBrainsMono-Regular", "JetBrainsMono-Bold".

Output each file separately. No commentary between files.
```

---

## 04b · Home screen prompt

```
Generate rn-app/src/screens/HomeScreen.tsx following LAYER 5 rules.

Props: onOpenArticle(slug), onOpenCategory().

Behaviour:
1. On mount, swr() two caches in parallel:
   - "articles:home" via listArticles({ limit: 30 })
   - "articles:featured" via featuredArticles(5)
2. Show LoadingState only if articles list is empty AND still loading.
3. Show ErrorState only if articles list is empty AND error occurred.
4. ListHeaderComponent contains:
   - A "Latest" title row with a "BROWSE BY CATEGORY →" tap target
     calling onOpenCategory.
   - A featured rail (horizontal ScrollView) of featured articles.
5. List uses FlatList rendering ArticleCard for each item.
6. Pull-to-refresh invalidates both caches and re-fetches.

No new visual primitives in this file — compose with existing
components.
```

## 04c · Detail screen prompt

```
Generate rn-app/src/screens/ArticleDetailScreen.tsx following LAYER 5.

Props: slug, onBack().

Behaviour:
1. On mount, swr() "article:<slug>" via articleBySlug(slug).
2. Back button at top calling onBack.
3. Hero image (full-bleed via HeroImage component).
4. Body section with:
   - Category pill + formatted publish date
   - Title (Syne, 34px)
   - Summary (DM Sans Bold, 18px)
   - Author chip + read time row
   - Divider
   - Article body. Include a minimal stripHtml() helper for the demo;
     in a production build, wire react-native-render-html instead.
   - "About the author" block if author.bio exists.

Show LoadingState while loading, ErrorState on failure with onRetry.
```

## 04d · Category screen prompt

```
Generate rn-app/src/screens/CategoryScreen.tsx following LAYER 5.

Props: onOpenArticle(slug), onBack().

Behaviour:
1. Tabs across the top for each ArticleCategory: news, feature,
   review, interview.
2. Active tab styled with ochre fill, inactive outline only.
3. On tab change, swr() "articles:cat:<category>" via
   listArticles({ category, limit: 30 }).
4. Show LoadingState / ErrorState / EmptyState as appropriate.
5. Pull-to-refresh invalidates the current category cache.

Reuse ArticleCard.
```

---

## What this prompt sequence demonstrates

The screen prompts are deliberately short. Most of the architecture
work was already done in prompts 00–03, which means each screen prompt
becomes a thin "compose existing pieces" instruction.

This is the agentic-coding leverage: structural decisions made once at
the top yield short, focused prompts for every subsequent file. The
total prompt-engineering effort scales with the number of architectural
patterns, not the number of files.

## What to verify

- [ ] No screen imports AsyncStorage directly
- [ ] No screen calls fetch() directly
- [ ] No component file does any data fetching
- [ ] Brand colours match exactly
- [ ] Pull-to-refresh actually invalidates and refetches

## After all four prompts

You have a complete, typed, cached, branded AEM-consuming mobile app.
Total elapsed time on a real engagement: a few hours, not a few weeks.
That's the point of the sample.
