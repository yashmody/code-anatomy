// app.config.ts · Expo configuration
//
// Environment-specific values (AEM base URL, namespace, auth token)
// are read from environment variables at build time and exposed to
// the app via expo-constants → Constants.expoConfig.extra.

import type { ExpoConfig } from "expo/config";

const config: ExpoConfig = {
  name: "AEM Sample",
  slug: "aem-rn-sample",
  version: "1.0.0",
  orientation: "portrait",
  icon: "./assets/icon.png",
  scheme: "aem-sample",
  userInterfaceStyle: "light",
  splash: {
    image: "./assets/splash.png",
    resizeMode: "contain",
    backgroundColor: "#ffffff",
  },
  ios: {
    supportsTablet: true,
    bundleIdentifier: "com.dept.aemsample",
  },
  android: {
    adaptiveIcon: {
      foregroundImage: "./assets/adaptive-icon.png",
      backgroundColor: "#FF4900",
    },
    package: "com.dept.aemsample",
  },
  web: {
    favicon: "./assets/favicon.png",
  },
  extra: {
    AEM_BASE_URL: process.env.AEM_BASE_URL ?? "https://publish-p123-e456.adobeaemcloud.com",
    AEM_NAMESPACE: process.env.AEM_NAMESPACE ?? "dept-sample",
    AEM_AUTH_TOKEN: process.env.AEM_AUTH_TOKEN,
  },
  plugins: ["expo-font"],
};

export default config;
