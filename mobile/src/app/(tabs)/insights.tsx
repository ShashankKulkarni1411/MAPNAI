// I1 Insights: what the biggest developing stories mean and what could happen next (GET /v1/users/{id}/insights),
// weighted towards what the reader follows, then a compact "your follows this week". New readers get the general
// picture plus a prompt to follow things, never a blank page.
import { router, useScrollToTop } from 'expo-router';
import { useRef } from 'react';
import { Pressable, RefreshControl, ScrollView, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { errorCopy } from '@/api/client';
import { useInsights } from '@/api/hooks';
import type { FollowChange } from '@/api/types';
import { Glyph } from '@/components/Glyph';
import { InsightCard } from '@/components/insights/InsightCard';
import { Txt } from '@/components/Txt';
import { CardSkeleton, EmptyState, IconButton, InlineError, SectionTitle } from '@/components/ui';
import { space } from '@/theme/tokens';
import { useTheme } from '@/theme/useTheme';

// "5 stories this week, up from 2 · Bumrah ruled out of series opener"
function changeLine(f: FollowChange): string {
  if (!f.this_week) return f.last_week ? `Quiet this week (${f.last_week} last week)` : 'Quiet this week';
  const n = `${f.this_week} ${f.this_week === 1 ? 'story' : 'stories'} this week`;
  const trend = f.this_week > f.last_week ? `, up from ${f.last_week}` : f.this_week < f.last_week ? `, down from ${f.last_week}` : '';
  return n + trend;
}

function FollowRow({ f, onInsight }: { f: FollowChange; onInsight?: () => void }) {
  const { c } = useTheme();
  const open = () => router.push({ pathname: '/entity/[key]', params: { key: f.key } });
  return (
    <Pressable onPress={onInsight ?? open} accessibilityRole="button" accessibilityLabel={`${f.name}. ${changeLine(f)}`}
      style={({ pressed }) => ({ flexDirection: 'row', alignItems: 'center', gap: 10, minHeight: 52, paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: c.hairline, opacity: pressed ? 0.7 : 1 })}>
      <View style={{ flex: 1, gap: 1 }}>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
          <Txt v="metaBold">{f.name}</Txt>
          {f.insight_story_id && <Txt v="label" color={c.highlight}>DEVELOPING</Txt>}
        </View>
        <Txt v="meta" muted numberOfLines={1}>
          {changeLine(f)}{f.top_story ? ` · ${f.top_story.title}` : ''}
        </Txt>
      </View>
      <Glyph name="chevron" color={c.ink2} />
    </Pressable>
  );
}

export default function Insights() {
  const { c } = useTheme();
  const insets = useSafeAreaInsets();
  const q = useInsights();
  const scroll = useRef<ScrollView>(null);
  useScrollToTop(scroll);
  const data = q.data;
  const follows = data?.follows ?? [];
  const insights = data?.insights ?? [];

  return (
    <ScrollView ref={scroll} style={{ backgroundColor: c.bg }}
      refreshControl={<RefreshControl refreshing={q.isRefetching} onRefresh={() => q.refetch()} tintColor={c.ink2} />}
      contentContainerStyle={{ paddingTop: insets.top + space.md, paddingHorizontal: space.gutter, paddingBottom: space.xxl * 2, maxWidth: 720, width: '100%', alignSelf: 'center' }}>
      <View style={{ flexDirection: 'row', alignItems: 'center' }}>
        <Txt v="screenTitle" accessibilityRole="header" style={{ flex: 1 }}>Insights</Txt>
        <IconButton icon="search" label="Search" onPress={() => router.push('/search')} />
      </View>
      <Txt v="meta" muted>What developing stories mean and what could happen next. AI analysis of our sources, not predictions.</Txt>

      <SectionTitle title="Developing stories"
        sub={data && !data.personalized && follows.length > 0 ? 'Nothing you follow is developing right now, so here are the biggest stories' : data?.personalized ? 'What you follow first' : 'The biggest stories right now'} />
      {q.isLoading && (<><CardSkeleton /><CardSkeleton /></>)}
      {q.isError && !data && <InlineError text={errorCopy(q.error, "Couldn't load insights. Try again.")} onRetry={() => q.refetch()} />}
      {data && insights.length === 0 && (
        <EmptyState text="No story is developing across several sources right now. Check back later." />
      )}
      {insights.map((i) => <InsightCard key={i.story_id} i={i} />)}

      {data && follows.length === 0 && (
        <View style={{ marginTop: space.md }}>
          <EmptyState text="Follow teams, players, films or places and their stories come first here, with what changed for each this week."
            action="Follow" onAction={() => router.push('/profile/add-follows')} />
        </View>
      )}
      {follows.length > 0 && (
        <>
          <SectionTitle title="Your follows this week" right={
            <Pressable onPress={() => router.push('/profile/add-follows')} hitSlop={8} accessibilityRole="button"><Txt v="metaBold">Add</Txt></Pressable>
          } />
          {follows.map((f) => {
            const story = insights.find((i) => i.story_id === f.insight_story_id);
            return <FollowRow key={f.key} f={f} onInsight={story ? () => router.push({ pathname: '/insight/[id]', params: { id: story.story_id } }) : undefined} />;
          })}
        </>
      )}
    </ScrollView>
  );
}
