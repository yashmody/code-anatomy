// EmptyState.tsx · shared empty/loading/error placeholders
import React from "react";
import { View, Text, ActivityIndicator, StyleSheet, Pressable } from "react-native";

export function LoadingState({ label = "Loading…" }: { label?: string }) {
  return (
    <View style={styles.center}>
      <ActivityIndicator size="large" color="#FF4900" />
      <Text style={styles.label}>{label}</Text>
    </View>
  );
}

export function EmptyState({ label = "Nothing here yet." }: { label?: string }) {
  return (
    <View style={styles.center}>
      <Text style={styles.empty}>{label}</Text>
    </View>
  );
}

export function ErrorState({
  message,
  onRetry,
}: {
  message: string;
  onRetry?: () => void;
}) {
  return (
    <View style={styles.center}>
      <Text style={styles.errLabel}>Something went wrong</Text>
      <Text style={styles.errMsg}>{message}</Text>
      {onRetry && (
        <Pressable onPress={onRetry} style={styles.retry}>
          <Text style={styles.retryText}>RETRY</Text>
        </Pressable>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  center: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    padding: 32,
    gap: 12,
  },
  label: {
    fontFamily: "JetBrainsMono-Regular",
    fontSize: 12,
    color: "#6f6f6f",
    letterSpacing: 1,
  },
  empty: {
    fontFamily: "Syne-Bold",
    fontSize: 18,
    color: "#6f6f6f",
    textAlign: "center",
  },
  errLabel: {
    fontFamily: "Syne-Bold",
    fontSize: 18,
    color: "#0a0a0a",
  },
  errMsg: {
    fontFamily: "DMSans-Regular",
    fontSize: 14,
    color: "#3f3f3f",
    textAlign: "center",
    maxWidth: 280,
  },
  retry: {
    borderWidth: 1,
    borderColor: "#FF4900",
    paddingHorizontal: 16,
    paddingVertical: 10,
    marginTop: 8,
  },
  retryText: {
    fontFamily: "JetBrainsMono-Bold",
    fontSize: 11,
    letterSpacing: 1.5,
    color: "#FF4900",
  },
});
