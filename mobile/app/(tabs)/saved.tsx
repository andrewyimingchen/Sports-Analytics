import { router } from "expo-router";

import { ListRow } from "@/components/rows";
import { BrandHeader, Card, EmptyState, Screen, SectionTitle } from "@/components/ui";
import { useApp } from "@/context/AppContext";

export default function SavedScreen() {
  const { saved } = useApp();
  const players = saved.filter((item) => item.type === "player");
  const teams = saved.filter((item) => item.type === "team");

  return (
    <Screen>
      <BrandHeader
        eyebrow="Your watch list"
        title="Saved"
        description="Players and teams you bookmark stay on this device for quick access."
      />
      {!saved.length ? (
        <EmptyState
          icon="bookmark-outline"
          title="Nothing saved yet"
          body="Open a player profile or team room and tap the bookmark button."
        />
      ) : null}
      {players.length ? (
        <>
          <SectionTitle title="Players" aside={`${players.length} SAVED`} />
          <Card>
            {players.map((item) => (
              <ListRow
                key={`player:${item.id}`}
                title={item.label}
                subtitle={item.subtitle ?? "Player profile"}
                onPress={() =>
                  router.push({
                    pathname: "/player/[id]",
                    params: { id: item.id, name: item.label }
                  })
                }
              />
            ))}
          </Card>
        </>
      ) : null}
      {teams.length ? (
        <>
          <SectionTitle title="Teams" aside={`${teams.length} SAVED`} />
          <Card>
            {teams.map((item) => (
              <ListRow
                key={`team:${item.id}`}
                title={item.label}
                subtitle={item.subtitle ?? "Team room"}
                onPress={() =>
                  router.push({
                    pathname: "/team/[code]",
                    params: { code: item.id }
                  })
                }
              />
            ))}
          </Card>
        </>
      ) : null}
    </Screen>
  );
}
