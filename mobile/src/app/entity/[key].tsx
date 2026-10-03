// S3 Entity page (MVP basic): name, follow control, your connection, latest stories, often mentioned with.
// GET /v1/entities/{key} and /stories are Proposed; until then the name comes from entity search and the
// stories from search. Entity types are never shown.
import { useQuery } from '@tanstack/react-query';
import { router, useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { ScrollView, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { api } from '@/api/endpoints';
import { followOf, useFollow, useProfile } from '@/api/hooks';
import { Button } from '@/components/Button';
import { Connection, ConnectionSheet } from '@/components/follow/ConnectionSheet';
import { SignalBars } from '@/components/Glyph';
import { StoryCard } from '@/components/story/StoryCard';
import { Txt } from '@/components/Txt';
import { CardSkeleton, EmptyState, SectionTitle, TopBar } from '@/components/ui';
import { importance, roleVerb, titleCaseKey } from '@/lib/labels';
import { useFeedback } from '@/state/feedback';
import { radius, space } from '@/theme/tokens';
import { useTheme } from '@/theme/useTheme';

export default function Entity() {
  const { c } = useTheme();
  const insets = useSafeAreaInsets();
  const { key } = useLocalSearchParams<{ key: string }>();
  const profile = useProfile();
  const follow = useFollow();
  const [editing, setEditing] = useState<Connection | null>(null);
  const hit = useQuery({
    queryKey: ['entity', key],
    queryFn: async () => (await api.searchEntities(key)).find((e) => e.key === key) ?? null,
  });
  const name = hit.data?.name ?? titleCaseKey(key);
  const stories = useQuery({ queryKey: ['entity-stories', key], queryFn: () => api.search(name) });
  const f = followOf(profile.data, key);
  const neighbours = (profile.data?.pi_topk ?? []).filter((p) => p.key !== key && p.score <= 0.1).slice(0, 8);

  const save = (conn: Connection) =>
    follow.mutate({ upsert: [{ key: conn.key, role: conn.role, weight: conn.weight }] }, {
      onSuccess: () => { setEditing(null); useFeedback.getState().showToast(`Following ${conn.name} · ${importance[conn.weight].label}`); },
    });
  const remove = (conn: Connection) =>
    follow.mutate({ remove: [conn.key] }, {
      onSuccess: () => {
        setEditing(null);
        useFeedback.getState().showToast(`Unfollowed ${conn.name}`, () => save(conn));
      },
    });

  return (
    <View style={{ flex: 1, backgroundColor: c.bg, paddingTop: insets.top }}>
      <TopBar title={name} />
      <ScrollView contentContainerStyle={{ padding: space.gutter, paddingBottom: insets.bottom + space.xxl, maxWidth: 720, width: '100%', alignSelf: 'center' }}>
        {/* 1 Header */}
        <Txt v="storyHeadline" accessibilityRole="header">{name}</Txt>
        {hit.data && <Txt v="meta" muted tabular>In {hit.data.mention_count} stories</Txt>}
        <View style={{ marginTop: space.md }}>
          {f ? (
            <Button label={`Following · ${importance[f.weight].label}`} variant="secondary"
              onPress={() => setEditing({ key, name, role: f.role, weight: f.weight })} />
          ) : (
            <Button label="Follow" onPress={() => setEditing({ key, name, role: 'follows', weight: 2 })} />
          )}
        </View>

        {/* 2 Your connection */}
        {f && (
          <View style={{ marginTop: space.lg, padding: space.lg, borderRadius: radius.card, backgroundColor: c.surface, borderWidth: 1, borderColor: c.hairline, gap: 6 }}>
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
              <Txt v="body">You {roleVerb[f.role]} {name} ({importance[f.weight].label}).</Txt>
              <SignalBars level={f.weight} color={c.ink} dim={c.hairline} />
            </View>
            <Txt v="meta" muted>{importance[f.weight].outcome}</Txt>
          </View>
        )}

        {/* 3 Latest */}
        <SectionTitle title={`Latest about ${name}`} />
        {stories.isLoading && <CardSkeleton />}
        {stories.data?.items.length === 0 && (
          <EmptyState text={`No stories about ${name} this week.${f ? ' Following still makes future news must-know.' : ''}`} />
        )}
        {stories.data?.items.slice(0, 10).map((s) => <StoryCard key={s.article_id} item={s} variant="compact" context="search" />)}

        {/* 5 Often mentioned with (from your connection graph while the entity endpoint is Proposed) */}
        {f && neighbours.length > 0 && (
          <>
            <SectionTitle title="Often mentioned with" sub="Often in the same stories, not necessarily related" />
            {neighbours.map((n) => (
              <View key={n.key} style={{ flexDirection: 'row', alignItems: 'center', minHeight: 52, borderBottomWidth: 1, borderBottomColor: c.hairline }}>
                <Txt v="body" style={{ flex: 1 }}>{n.name ?? titleCaseKey(n.key)}</Txt>
                <Button label="Open" variant="text" small onPress={() => router.push({ pathname: '/entity/[key]', params: { key: n.key } })} />
              </View>
            ))}
          </>
        )}

        {/* 7 Ask */}
        <Button label={`Ask about ${name}`} variant="highlight" icon="ask" style={{ marginTop: space.xxl }}
          onPress={() => router.push({ pathname: '/ask', params: { q: `What's the latest on ${name}?` } })} />
      </ScrollView>
      <ConnectionSheet value={editing} onClose={() => setEditing(null)} onSave={save} saving={follow.isPending}
        onRemove={f ? (conn) => remove(conn) : undefined} />
    </View>
  );
}
