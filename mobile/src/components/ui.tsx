import Ionicons from "@expo/vector-icons/Ionicons";
import { PropsWithChildren, ReactNode } from "react";
import {
  ActivityIndicator,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleProp,
  StyleSheet,
  Text,
  View,
  ViewStyle
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { colors, radius, spacing } from "@/theme";

export function Screen({
  children,
  refreshing = false,
  onRefresh,
  contentStyle
}: PropsWithChildren<{
  refreshing?: boolean;
  onRefresh?: () => void;
  contentStyle?: StyleProp<ViewStyle>;
}>) {
  return (
    <SafeAreaView edges={["top"]} style={styles.safe}>
      <ScrollView
        contentContainerStyle={[styles.screen, contentStyle]}
        keyboardShouldPersistTaps="handled"
        refreshControl={
          onRefresh ? (
            <RefreshControl
              refreshing={refreshing}
              onRefresh={onRefresh}
              tintColor={colors.orange}
              colors={[colors.orange]}
            />
          ) : undefined
        }
      >
        {children}
      </ScrollView>
    </SafeAreaView>
  );
}

export function BrandHeader({
  eyebrow,
  title,
  description,
  action
}: {
  eyebrow: string;
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <View style={styles.header}>
      <View style={styles.headerTop}>
        <View style={styles.brandRow}>
          <View style={styles.ball}>
            <Text style={styles.ballText}>PL</Text>
          </View>
          <Text style={styles.brand}>
            POSSESSION <Text style={styles.brandAccent}>LAB</Text>
          </Text>
        </View>
        {action}
      </View>
      <Text style={styles.eyebrow}>{eyebrow.toUpperCase()}</Text>
      <Text style={styles.title}>{title.toUpperCase()}</Text>
      {description ? <Text style={styles.description}>{description}</Text> : null}
    </View>
  );
}

export function Card({
  children,
  style
}: PropsWithChildren<{ style?: StyleProp<ViewStyle> }>) {
  return <View style={[styles.card, style]}>{children}</View>;
}

export function SectionTitle({
  title,
  aside
}: {
  title: string;
  aside?: string;
}) {
  return (
    <View style={styles.sectionTitleRow}>
      <Text style={styles.sectionTitle}>{title.toUpperCase()}</Text>
      {aside ? <Text style={styles.sectionAside}>{aside}</Text> : null}
    </View>
  );
}

export function Stat({
  label,
  value,
  accent = false
}: {
  label: string;
  value: string;
  accent?: boolean;
}) {
  return (
    <View style={styles.stat}>
      <Text style={[styles.statValue, accent && styles.statAccent]}>{value}</Text>
      <Text style={styles.statLabel}>{label.toUpperCase()}</Text>
    </View>
  );
}

export function Pill({
  label,
  selected,
  onPress
}: {
  label: string;
  selected?: boolean;
  onPress?: () => void;
}) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ selected }}
      onPress={onPress}
      style={({ pressed }) => [
        styles.pill,
        selected && styles.pillSelected,
        pressed && styles.pressed
      ]}
    >
      <Text style={[styles.pillText, selected && styles.pillTextSelected]}>{label}</Text>
    </Pressable>
  );
}

export function IconButton({
  icon,
  label,
  onPress,
  active = false
}: {
  icon: keyof typeof Ionicons.glyphMap;
  label: string;
  onPress: () => void;
  active?: boolean;
}) {
  return (
    <Pressable
      accessibilityLabel={label}
      accessibilityRole="button"
      onPress={onPress}
      style={({ pressed }) => [
        styles.iconButton,
        active && styles.iconButtonActive,
        pressed && styles.pressed
      ]}
    >
      <Ionicons name={icon} size={20} color={active ? colors.night : colors.paper} />
    </Pressable>
  );
}

export function PrimaryButton({
  label,
  onPress,
  disabled = false,
  icon
}: {
  label: string;
  onPress: () => void;
  disabled?: boolean;
  icon?: keyof typeof Ionicons.glyphMap;
}) {
  return (
    <Pressable
      accessibilityRole="button"
      disabled={disabled}
      onPress={onPress}
      style={({ pressed }) => [
        styles.primaryButton,
        disabled && styles.disabled,
        pressed && !disabled && styles.pressed
      ]}
    >
      {icon ? <Ionicons name={icon} size={18} color={colors.night} /> : null}
      <Text style={styles.primaryButtonText}>{label.toUpperCase()}</Text>
    </Pressable>
  );
}

export function LoadingState({ label = "Reading the floor…" }: { label?: string }) {
  return (
    <View style={styles.state}>
      <ActivityIndicator color={colors.orange} size="small" />
      <Text style={styles.stateText}>{label}</Text>
    </View>
  );
}

export function ErrorState({
  message,
  onRetry
}: {
  message: string;
  onRetry?: () => void;
}) {
  return (
    <Card style={styles.error}>
      <Ionicons name="cloud-offline-outline" size={24} color={colors.orange} />
      <View style={styles.errorCopy}>
        <Text style={styles.errorTitle}>CAN’T LOAD THIS VIEW</Text>
        <Text style={styles.errorText}>{message}</Text>
      </View>
      {onRetry ? <IconButton icon="refresh" label="Retry" onPress={onRetry} /> : null}
    </Card>
  );
}

export function EmptyState({
  icon = "basketball-outline",
  title,
  body
}: {
  icon?: keyof typeof Ionicons.glyphMap;
  title: string;
  body: string;
}) {
  return (
    <View style={styles.empty}>
      <Ionicons name={icon} size={34} color={colors.muted2} />
      <Text style={styles.emptyTitle}>{title.toUpperCase()}</Text>
      <Text style={styles.emptyBody}>{body}</Text>
    </View>
  );
}

export function StaleBanner() {
  return (
    <View style={styles.stale}>
      <Ionicons name="cloud-offline-outline" size={14} color={colors.night} />
      <Text style={styles.staleText}>OFFLINE COPY · PULL TO RETRY</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.night },
  screen: {
    paddingHorizontal: spacing.md,
    paddingBottom: 120,
    gap: spacing.md,
    backgroundColor: colors.night
  },
  header: { paddingTop: spacing.sm, paddingBottom: spacing.lg, gap: spacing.sm },
  headerTop: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  brandRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  ball: {
    width: 34,
    height: 34,
    borderRadius: 17,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: colors.orange
  },
  ballText: { color: colors.night, fontSize: 11, fontWeight: "900" },
  brand: { color: colors.paper, fontSize: 14, fontWeight: "900", letterSpacing: 0.5 },
  brandAccent: { color: colors.orange },
  eyebrow: {
    color: colors.orangeSoft,
    fontSize: 10,
    fontWeight: "800",
    letterSpacing: 2,
    marginTop: spacing.lg
  },
  title: {
    color: colors.paper,
    fontSize: 42,
    lineHeight: 43,
    fontWeight: "900",
    letterSpacing: -1.5
  },
  description: { color: colors.muted, fontSize: 14, lineHeight: 21, maxWidth: 520 },
  card: {
    backgroundColor: colors.panel,
    borderColor: colors.line,
    borderWidth: StyleSheet.hairlineWidth,
    borderRadius: radius.md,
    padding: spacing.md
  },
  sectionTitleRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginTop: spacing.sm
  },
  sectionTitle: { color: colors.paper, fontSize: 18, fontWeight: "900", letterSpacing: 0.3 },
  sectionAside: { color: colors.muted2, fontSize: 10, fontWeight: "700" },
  stat: { flex: 1, minWidth: 72 },
  statValue: { color: colors.paper, fontSize: 24, fontWeight: "900", letterSpacing: -0.6 },
  statAccent: { color: colors.lime },
  statLabel: { color: colors.muted2, fontSize: 9, fontWeight: "800", marginTop: 3 },
  pill: {
    minHeight: 40,
    paddingHorizontal: spacing.md,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: colors.line,
    backgroundColor: colors.panel
  },
  pillSelected: { backgroundColor: colors.paper, borderColor: colors.paper },
  pillText: { color: colors.muted, fontWeight: "800", fontSize: 12 },
  pillTextSelected: { color: colors.night },
  pressed: { opacity: 0.72, transform: [{ scale: 0.985 }] },
  iconButton: {
    width: 42,
    height: 42,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 21,
    borderWidth: 1,
    borderColor: colors.line,
    backgroundColor: colors.panel
  },
  iconButtonActive: { backgroundColor: colors.lime, borderColor: colors.lime },
  primaryButton: {
    minHeight: 52,
    flexDirection: "row",
    gap: spacing.sm,
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: spacing.lg,
    borderRadius: radius.sm,
    backgroundColor: colors.orange
  },
  primaryButtonText: {
    color: colors.night,
    fontWeight: "900",
    fontSize: 12,
    letterSpacing: 0.7
  },
  disabled: { opacity: 0.38 },
  state: { minHeight: 180, alignItems: "center", justifyContent: "center", gap: spacing.md },
  stateText: { color: colors.muted, fontSize: 13 },
  error: { flexDirection: "row", alignItems: "center", gap: spacing.md },
  errorCopy: { flex: 1, gap: 4 },
  errorTitle: { color: colors.paper, fontSize: 12, fontWeight: "900" },
  errorText: { color: colors.muted, fontSize: 12, lineHeight: 17 },
  empty: { minHeight: 230, alignItems: "center", justifyContent: "center", gap: spacing.sm },
  emptyTitle: { color: colors.paper, fontSize: 16, fontWeight: "900", marginTop: spacing.sm },
  emptyBody: { color: colors.muted, textAlign: "center", maxWidth: 280, lineHeight: 20 },
  stale: {
    alignSelf: "flex-start",
    flexDirection: "row",
    gap: spacing.xs,
    alignItems: "center",
    backgroundColor: colors.lime,
    borderRadius: radius.pill,
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs
  },
  staleText: { color: colors.night, fontSize: 9, fontWeight: "900", letterSpacing: 0.5 }
});
