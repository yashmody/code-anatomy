// =================================================================
// HeroImage.tsx · DAM-backed hero image with aspect-ratio preservation
// =================================================================
//
// Reserves layout space using width/height from AEM, falling back to
// an explicit aspectRatio prop. This prevents CLS (cumulative layout
// shift) — the same discipline you'd apply on the web.

import React from "react";
import { Image, View, StyleSheet } from "react-native";
import type { ImageRef } from "../lib/model";

interface Props {
  image: ImageRef;
  aspectRatio?: number; // fallback if image.width/height absent
}

export function HeroImage({ image, aspectRatio = 16 / 9 }: Props) {
  const ratio =
    image.width && image.height ? image.width / image.height : aspectRatio;

  return (
    <View style={[styles.wrap, { aspectRatio: ratio }]}>
      <Image
        source={{ uri: image._publishUrl }}
        style={styles.img}
        resizeMode="cover"
        accessible
        accessibilityIgnoresInvertColors
      />
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    width: "100%",
    backgroundColor: "#f6f5f1",
  },
  img: {
    width: "100%",
    height: "100%",
  },
});
