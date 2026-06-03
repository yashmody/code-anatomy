// =================================================================
// App.tsx · root component, navigation, AEM client configuration
// =================================================================
//
// Stateful "router" using a small useReducer — enough for a 3-screen
// sample without pulling in a navigation library. In a real app, this
// is where you'd mount react-navigation or expo-router instead.

import React, { useEffect, useReducer } from "react";
import { SafeAreaView, StatusBar, StyleSheet, View } from "react-native";
import Constants from "expo-constants";

import { configureClient } from "./src/lib/api";
import { HomeScreen } from "./src/screens/HomeScreen";
import { ArticleDetailScreen } from "./src/screens/ArticleDetailScreen";
import { CategoryScreen } from "./src/screens/CategoryScreen";

// -----------------------------------------------------------------
// Configure the AEM client once at mount.
// Values come from app.config.ts → expo-constants.
// -----------------------------------------------------------------
configureClient({
  baseUrl: Constants.expoConfig?.extra?.AEM_BASE_URL ?? "https://publish.example.com",
  namespace: Constants.expoConfig?.extra?.AEM_NAMESPACE ?? "dept-sample",
  authToken: Constants.expoConfig?.extra?.AEM_AUTH_TOKEN,
});

// -----------------------------------------------------------------
// Tiny route state machine — the only events the app handles
// -----------------------------------------------------------------
type Route =
  | { name: "home" }
  | { name: "article"; slug: string }
  | { name: "category" };

type Action =
  | { type: "open-home" }
  | { type: "open-article"; slug: string }
  | { type: "open-category" };

function routeReducer(state: Route, action: Action): Route {
  switch (action.type) {
    case "open-home":
      return { name: "home" };
    case "open-article":
      return { name: "article", slug: action.slug };
    case "open-category":
      return { name: "category" };
    default:
      return state;
  }
}

export default function App() {
  const [route, dispatch] = useReducer(routeReducer, { name: "home" });

  // Hardware back button (Android) handled minimally for the demo.
  useEffect(() => {
    // In a real app, react-navigation handles this.
  }, []);

  return (
    <SafeAreaView style={styles.root}>
      <StatusBar barStyle="dark-content" />
      <View style={styles.container}>
        {route.name === "home" && (
          <HomeScreen
            onOpenArticle={(slug) => dispatch({ type: "open-article", slug })}
            onOpenCategory={() => dispatch({ type: "open-category" })}
          />
        )}
        {route.name === "article" && (
          <ArticleDetailScreen
            slug={route.slug}
            onBack={() => dispatch({ type: "open-home" })}
          />
        )}
        {route.name === "category" && (
          <CategoryScreen
            onOpenArticle={(slug) => dispatch({ type: "open-article", slug })}
            onBack={() => dispatch({ type: "open-home" })}
          />
        )}
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: "#fff" },
  container: { flex: 1 },
});
