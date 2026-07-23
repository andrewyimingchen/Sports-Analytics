import Ionicons from "@expo/vector-icons/Ionicons";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors, radius, spacing } from "@/theme";

export function ListRow({
  title,
  subtitle,
  value,
  onPress,
  index
}: {
  title: string;
  subtitle?: string;
  value?: string;
  onPress?: () => void;
  index?: number;
}) {
  return (
    <Pressable
      accessibilityRole={onPress ? "button" : undefined}
      onPress={onPress}
      style={({ pressed }) => [styles.row, pressed && styles.pressed]}
    >
      {index !== undefined ? (
        <Text style={styles.index}>{String(index + 1).padStart(2, "0")}</Text>
      ) : null}
      <View style={styles.copy}>
        <Text numberOfLines={1} style={styles.title}>{title}</Text>
        {subtitle ? <Text numberOfLines={1} style={styles.subtitle}>{subtitle}</Text> : null}
      </View>
      {value ? <Text style={styles.value}>{value}</Text> : null}
      {onPress ? <Ionicons name="chevron-forward" size={16} color={colors.muted2} /> : null}
    </Pressable>
  );
}

export function ProgressBar({
  value,
  color = colors.orange
}: {
  value: number;
  color?: string;
}) {
  const safe = Math.min(100, Math.max(0, value));
  return (
    <View style={styles.track}>
      <View style={[styles.fill, { width: `${safe}%`, backgroundColor: color }]} />
    </View>
  );
}

export function DataRow({
  label,
  value,
  last = false
}: {
  label: string;
  value: string;
  last?: boolean;
}) {
  return (
    <View style={[styles.dataRow, last && styles.last]}>
      <Text style={styles.dataLabel}>{label}</Text>
      <Text style={styles.dataValue}>{value}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  row: {
    minHeight: 62,
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    paddingVertical: spacing.sm,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.line
  },
  pressed: { opacity: 0.65 },
  index: { color: colors.orangeSoft, fontSize: 10, fontWeight: "900", width: 22 },
  copy: { flex: 1, gap: 3 },
  title: { color: colors.paper, fontSize: 14, fontWeight: "800" },
  subtitle: { color: colors.muted, fontSize: 11 },
  value: { color: colors.lime, fontSize: 17, fontWeight: "900" },
  track: {
    height: 6,
    overflow: "hidden",
    backgroundColor: colors.panel2,
    borderRadius: radius.pill
  },
  fill: { height: "100%", borderRadius: radius.pill },
  dataRow: {
    minHeight: 48,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: spacing.md,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.line
  },
  last: { borderBottomWidth: 0 },
  dataLabel: { flex: 1, color: colors.muted, fontSize: 12 },
  dataValue: { color: colors.paper, fontSize: 13, fontWeight: "800" }
});
