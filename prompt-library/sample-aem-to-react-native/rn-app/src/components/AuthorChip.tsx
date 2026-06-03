// AuthorChip.tsx · avatar + name in a single row
import React from "react";
import { View, Image, Text, StyleSheet } from "react-native";
import type { Author } from "../lib/model";

export function AuthorChip({ author }: { author: Author }) {
  return (
    <View style={styles.row}>
      {author.avatar && (
        <Image source={{ uri: author.avatar._publishUrl }} style={styles.avatar} />
      )}
      <Text style={styles.name} numberOfLines={1}>
        {author.name}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: "row", alignItems: "center", gap: 8, flex: 1 },
  avatar: {
    width: 22,
    height: 22,
    borderRadius: 11,
    backgroundColor: "#f6f5f1",
  },
  name: {
    fontFamily: "DMSans-Bold",
    fontSize: 12,
    color: "#0a0a0a",
    flexShrink: 1,
  },
});
