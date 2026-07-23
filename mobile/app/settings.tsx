import Ionicons from "@expo/vector-icons/Ionicons";
import { useState } from "react";
import { Alert, StyleSheet, Text, TextInput, View } from "react-native";

import { getJson } from "@/api/client";
import {
  BrandHeader,
  Card,
  PrimaryButton,
  Screen,
  SectionTitle
} from "@/components/ui";
import { useApp } from "@/context/AppContext";
import { colors, radius, spacing } from "@/theme";

interface Health {
  status: string;
}

export default function SettingsScreen() {
  const { baseUrl, apiKey, setConnection } = useApp();
  const [urlDraft, setUrlDraft] = useState<string | null>(null);
  const [keyDraft, setKeyDraft] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const url = urlDraft ?? baseUrl;
  const key = keyDraft ?? apiKey;

  async function saveAndTest() {
    setBusy(true);
    try {
      await setConnection(url, key.trim());
      const result = await getJson<Health>(url, "/healthz", {
        apiKey: key.trim(),
        cache: false
      });
      Alert.alert("Connected", `POSSESSION LAB reported “${result.data.status}”.`);
    } catch (error) {
      Alert.alert(
        "Connection failed",
        error instanceof Error ? error.message : "Check the server address."
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <Screen>
      <BrandHeader
        eyebrow="App settings"
        title="Connection"
        description="Point the app at your POSSESSION LAB FastAPI server. A remote deployment should use HTTPS."
      />
      <SectionTitle title="Backend" />
      <Card style={styles.form}>
        <View style={styles.field}>
          <Text style={styles.label}>SERVER URL</Text>
          <TextInput
            accessibilityLabel="Server URL"
            autoCapitalize="none"
            autoCorrect={false}
            keyboardType="url"
            placeholder="https://analytics.example.com"
            placeholderTextColor={colors.muted2}
            style={styles.input}
            value={url}
            onChangeText={setUrlDraft}
          />
          <Text style={styles.help}>
            Android emulator default: http://10.0.2.2:8000. iOS simulator: http://127.0.0.1:8000.
            A physical phone needs your computer’s LAN address.
          </Text>
        </View>
        <View style={styles.field}>
          <Text style={styles.label}>API KEY · OPTIONAL</Text>
          <TextInput
            accessibilityLabel="API key"
            autoCapitalize="none"
            autoCorrect={false}
            placeholder="Required only by protected deployments"
            placeholderTextColor={colors.muted2}
            secureTextEntry
            style={styles.input}
            value={key}
            onChangeText={setKeyDraft}
          />
          <View style={styles.secureRow}>
            <Ionicons name="lock-closed" size={13} color={colors.lime} />
            <Text style={styles.secureText}>Stored in iOS Keychain / Android Keystore</Text>
          </View>
        </View>
        <PrimaryButton
          label={busy ? "Testing…" : "Save and test"}
          icon="wifi"
          disabled={busy || !url.trim()}
          onPress={saveAndTest}
        />
      </Card>

      <SectionTitle title="Privacy" />
      <Card>
        <Text style={styles.aboutTitle}>YOUR DATA STAYS YOURS</Text>
        <Text style={styles.about}>
          Saved players, teams, and cached responses remain on the device. The app does not include
          advertising or analytics SDKs. Basketball data requests go only to the server configured above.
        </Text>
      </Card>

      <SectionTitle title="About" />
      <Card>
        <Text style={styles.aboutTitle}>POSSESSION LAB MOBILE · 1.0.0</Text>
        <Text style={styles.about}>
          NBA intelligence, matchup probabilities, and transparent basketball models. Built as one
          React Native app for iOS and Android.
        </Text>
      </Card>
    </Screen>
  );
}

const styles = StyleSheet.create({
  form: { gap: spacing.lg },
  field: { gap: spacing.sm },
  label: { color: colors.muted, fontSize: 10, fontWeight: "900", letterSpacing: 1.1 },
  input: {
    minHeight: 52,
    color: colors.paper,
    backgroundColor: colors.night2,
    borderWidth: 1,
    borderColor: colors.line,
    borderRadius: radius.sm,
    paddingHorizontal: spacing.md
  },
  help: { color: colors.muted2, fontSize: 10, lineHeight: 16 },
  secureRow: { flexDirection: "row", alignItems: "center", gap: spacing.xs },
  secureText: { color: colors.muted, fontSize: 10 },
  aboutTitle: { color: colors.lime, fontSize: 10, fontWeight: "900", marginBottom: spacing.sm },
  about: { color: colors.muted, fontSize: 12, lineHeight: 19 }
});
