// I1 Insights (MVP lite): your world this week, a connections list, and the biggest stories of the week.
// Developing stories, sparklines, tone bars and recaps need GET /v1/users/{id}/insights (Proposed, next phase).
import { router, useScrollToTop } from 'expo-router';
import { useRef } from 'react';
import { Pressable, ScrollView, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { useProfile, useTop } from '@/api/hooks';
import { Glyph, SignalBars } from '@/components/Glyph';
import { openStory } from '@/components/story/StoryCard';
import { Txt } from '@/components/Txt';
import { CardSkeleton, EmptyState, IconButton, SectionTitle } from '@/components/ui';
import { titleCaseKey, topicLabel } from '@/lib/labels';
import { radius, space } from '@/theme/tokens';
import { useTheme } from '@/theme/useTheme';

export default function Insights() {
  const { c } = useTheme();
  const insets = useSafeAreaInsets();
  const profile = useProfile();
  const week = useTop(24 * 7);
  const scroll = useRef<ScrollView>(null);
  useScrollToTop(scroll);
  const follows = profile.data?.exposures ?? [];
  const connected = (profile.data?.pi_topk ?? []).filter((p) => !follows.some((f) => f.key === p.key)).slice(0, 20);

  return (
    <ScrollView ref={scroll} style={{ backgroundColor: c.bg }}
      contentContainerStyle={{ paddingTop: insets.top + space.md, paddingHorizontal: space.gutter, paddingBottom: space.xxl * 2, maxWidth: 720, width: '100%', alignSelf: 'center' }}>
      <View style={{ flexDirection: 'row', alignItems: 'center' }}>
        <Txt v="screenTitle" accessibilityRole="header" style={{ flex: 1 }}>Insights</Txt>
        <IconButton icon="search" label="Search" onPress={() => router.push('/search')} />
      </View>

      <SectionTitle title="Your world" sub="What you follow" />
      {follows.length === 0 ? (
        <EmptyState text="Follow teams, players or films to see what's developing around them." action="Follow" onAction={() => router.push('/profile/add-follows')} />
      ) : follows.map((f) => (
        <Pressable key={f.key} onPress={() => router.push({ pathname: '/entity/[key]', params: { key: f.key } })} accessibilityRole="button"
          style={{ flexDirection: 'row', alignItems: 'center', gap: 10, minHeight: 52, borderBottomWidth: 1, borderBottomColor: c.hairline }}>
          <Txt v="body" style={{ flex: 1 }}>{f.name}</Txt>
          <SignalBars level={f.weight} color={c.ink} dim={c.hairline} />
          <Glyph name="chevron" color={c.ink2} />
        </Pressable>
      ))}

      {connected.length > 0 && (
        <>
          <SectionTitle title="Connected to what you follow" sub="Links come from stories that mention both. They show association, not a relationship." />
          <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 6 }}>
            {connected.map((p) => (
              <Pressable key={p.key} onPress={() => router.push({ pathname: '/entity/[key]', params: { key: p.key } })} accessibilityRole="button"
                style={{ borderWidth: 1, borderColor: c.hairline, borderRadius: radius.chip, paddingHorizontal: 12, minHeight: 36, justifyContent: 'center' }}>
                <Txt v="meta">{p.name ?? titleCaseKey(p.key)}</Txt>
              </Pressable>
            ))}
          </View>
        </>
      )}

      <SectionTitle title="Biggest this week" sub="Across sports, film and general news, whatever you follow" />
      {week.isLoading && <CardSkeleton />}
      {(week.data ?? []).slice(0, 5).map((s) => (
        <Pressable key={s.article_id} onPress={() => openStory(s, 'deeplink')} accessibilityRole="button"
          style={{ paddingVertical: 12, borderBottomWidth: 1, borderBottomColor: c.hairline, gap: 2 }}>
          <Txt v="compactHeadline">{s.title}</Txt>
          <Txt v="meta" muted>{topicLabel(s.topic)} · {s.cluster_size} sources</Txt>
        </Pressable>
      ))}
    </ScrollView>
  );
}
