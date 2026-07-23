import { router } from "expo-router";
import { useEffect, useState } from "react";
import { StyleSheet, TextInput, View } from "react-native";

import type { PlayerSearchResult } from "@/api/types";
import { ListRow } from "@/components/rows";
import {
  BrandHeader,
  Card,
  EmptyState,
  ErrorState,
  LoadingState,
  Screen
} from "@/components/ui";
import { useRemote } from "@/hooks/useRemote";
import { colors, radius, spacing } from "@/theme";

export default function PlayersScreen() {
  const [input, setInput] = useState("");
  const [query, setQuery] = useState("");

  useEffect(() => {
    const timer = setTimeout(() => setQuery(input.trim()), 320);
    return () => clearTimeout(timer);
  }, [input]);

  const remote = useRemote<PlayerSearchResult[]>(
    query.length >= 3 ? "/players/search" : null,
    { q: query }
  );

  return (
    <Screen>
      <BrandHeader
        eyebrow="Player intelligence"
        title="Find a player"
        description="Search any NBA player, then open career trends, ratings, percentiles, and recent form."
      />
      <View style={styles.searchWrap}>
        <TextInput
          accessibilityLabel="Player name"
          autoCapitalize="words"
          autoCorrect={false}
          placeholder="Search by name…"
          placeholderTextColor={colors.muted2}
          returnKeyType="search"
          style={styles.input}
          value={input}
          onChangeText={setInput}
        />
      </View>

      {remote.loading && query.length >= 3 ? <LoadingState label="Searching rosters…" /> : null}
      {remote.error ? <ErrorState message={remote.error} /> : null}
      {!remote.loading && query.length < 3 ? (
        <EmptyState
          icon="search-outline"
          title="Start with a name"
          body="Type at least three letters. Active and historical players are both searchable."
        />
      ) : null}
      {!remote.loading && query.length >= 3 && remote.data?.length === 0 ? (
        <EmptyState
          icon="person-outline"
          title="No players found"
          body="Try a full last name or check the spelling."
        />
      ) : null}
      {remote.data?.length ? (
        <Card>
          {remote.data.map((player) => (
            <ListRow
              key={player.id}
              title={player.full_name}
              subtitle={player.is_active ? "Active player" : "Historical player"}
              onPress={() =>
                router.push({
                  pathname: "/player/[id]",
                  params: { id: player.id, name: player.full_name }
                })
              }
            />
          ))}
        </Card>
      ) : null}
    </Screen>
  );
}

const styles = StyleSheet.create({
  searchWrap: { marginTop: -spacing.sm },
  input: {
    minHeight: 56,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.line,
    backgroundColor: colors.panel,
    color: colors.paper,
    fontSize: 16,
    paddingHorizontal: spacing.md
  }
});
