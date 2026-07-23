import * as Haptics from "expo-haptics";
import { useLocalSearchParams } from "expo-router";
import { Image, StyleSheet, Text, View } from "react-native";

import type { JsonRecord, PlayerGames, PlayerInsights } from "@/api/types";
import { ListRow, ProgressBar } from "@/components/rows";
import {
  BrandHeader,
  Card,
  ErrorState,
  IconButton,
  LoadingState,
  Screen,
  SectionTitle,
  StaleBanner,
  Stat
} from "@/components/ui";
import { useApp } from "@/context/AppContext";
import { number, statPercentile } from "@/lib/format";
import { useRemote } from "@/hooks/useRemote";
import { apiUrl } from "@/lib/url";
import { colors, spacing } from "@/theme";

function gameValue(game: JsonRecord, key: string): string {
  return number(game[key], 0);
}

export default function PlayerDetailScreen() {
  const params = useLocalSearchParams<{ id: string; name?: string }>();
  const id = Number(params.id);
  const { baseUrl, isSaved, toggleFavorite } = useApp();
  const insights = useRemote<PlayerInsights>(`/players/${id}/insights`);
  const career = useRemote<JsonRecord[]>(`/players/${id}/career`);
  const games = useRemote<PlayerGames>(`/players/${id}/games`, { limit: 8 });
  const name = insights.data?.player ?? params.name ?? "Player";
  const item = { type: "player" as const, id, label: name, subtitle: insights.data?.season };
  const saved = isSaved(item);
  const ratings = insights.data?.ratings ?? {};
  const percentiles = Object.entries(insights.data?.league_percentiles ?? {})
    .sort((a, b) => b[1] - a[1])
    .slice(0, 6);

  async function favorite() {
    await toggleFavorite(item);
    await Haptics.selectionAsync();
  }

  const reload = () => Promise.all([insights.reload(), career.reload(), games.reload()]).then(() => undefined);
  const refreshing = insights.refreshing || career.refreshing || games.refreshing;

  return (
    <Screen refreshing={refreshing} onRefresh={reload}>
      <BrandHeader
        eyebrow={insights.data ? `${insights.data.season} · ${ratings.TEAM_ABBREVIATION ?? "NBA"}` : "Player profile"}
        title={name}
        action={
          <IconButton
            icon={saved ? "bookmark" : "bookmark-outline"}
            label={saved ? "Remove from saved" : "Save player"}
            active={saved}
            onPress={favorite}
          />
        }
      />
      {insights.stale || career.stale || games.stale ? <StaleBanner /> : null}
      {insights.loading && !insights.data ? <LoadingState label="Building player profile…" /> : null}
      {insights.error && !insights.data ? (
        <ErrorState message={insights.error} onRetry={insights.reload} />
      ) : null}
      {insights.data ? (
        <>
          <Card style={styles.hero}>
            <Image
              accessibilityLabel={`${name} headshot`}
              source={{ uri: apiUrl(baseUrl, `/players/${id}/headshot`) }}
              style={styles.headshot}
            />
            <View style={styles.heroCopy}>
              <Text style={styles.position}>
                {insights.data.position_group ?? "NBA PLAYER"}
              </Text>
              <Text style={styles.take}>{insights.data.scouting_take}</Text>
            </View>
          </Card>
          <View style={styles.statRow}>
            <Card style={styles.statCard}>
              <Stat label="Net rating" value={number(ratings.NET_RATING)} accent />
            </Card>
            <Card style={styles.statCard}>
              <Stat label="DPM" value={number(ratings.DPM)} />
            </Card>
          </View>

          <SectionTitle title="League percentiles" aside="0–100" />
          <Card style={styles.percentileCard}>
            {percentiles.map(([label, value]) => (
              <View key={label} style={styles.percentile}>
                <View style={styles.percentileTop}>
                  <Text style={styles.percentileLabel}>{label.replaceAll("_", " ")}</Text>
                  <Text style={styles.percentileValue}>{statPercentile(value)}</Text>
                </View>
                <ProgressBar value={value} color={value >= 75 ? colors.lime : colors.orange} />
              </View>
            ))}
          </Card>
        </>
      ) : null}

      {career.data?.length ? (
        <>
          <SectionTitle title="Career arc" aside={`${career.data.length} SEASONS`} />
          <Card>
            {career.data.slice().reverse().slice(0, 8).map((row) => (
              <ListRow
                key={String(row.SEASON_ID)}
                title={String(row.SEASON_ID)}
                subtitle={`${number(row.REB)} REB · ${number(row.AST)} AST`}
                value={`${number(row.PTS)} PTS`}
              />
            ))}
          </Card>
        </>
      ) : null}

      {games.data?.games.length ? (
        <>
          <SectionTitle title="Recent form" aside={games.data.season} />
          <Card>
            {games.data.games.map((game, index) => (
              <ListRow
                key={`${game.GAME_DATE}-${index}`}
                title={String(game.MATCHUP ?? game.GAME_DATE ?? "Game")}
                subtitle={`${game.WL ?? "—"} · ${gameValue(game, "REB")} REB · ${gameValue(game, "AST")} AST`}
                value={`${gameValue(game, "PTS")} PTS`}
              />
            ))}
          </Card>
        </>
      ) : null}
    </Screen>
  );
}

const styles = StyleSheet.create({
  hero: { minHeight: 190, overflow: "hidden", flexDirection: "row", alignItems: "flex-end", paddingBottom: 0 },
  headshot: { width: 145, height: 180, resizeMode: "contain", marginLeft: -spacing.md },
  heroCopy: { flex: 1, paddingBottom: spacing.lg, gap: spacing.sm },
  position: { color: colors.orangeSoft, fontSize: 10, fontWeight: "900", letterSpacing: 1.2 },
  take: { color: colors.paper, fontSize: 13, lineHeight: 20, fontWeight: "600" },
  statRow: { flexDirection: "row", gap: spacing.sm },
  statCard: { flex: 1 },
  percentileCard: { gap: spacing.md },
  percentile: { gap: spacing.sm },
  percentileTop: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  percentileLabel: { color: colors.muted, fontSize: 11, textTransform: "uppercase" },
  percentileValue: { color: colors.paper, fontSize: 12, fontWeight: "900" }
});
