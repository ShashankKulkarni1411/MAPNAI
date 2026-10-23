// I3 Insight: the full analysis of one developing story: what happened, why it matters (and to you), every possible
// outcome with its signals, what to watch next, what you can do, and the sources each claim rests on. AI analysis,
// not a prediction.
import { router, useLocalSearchParams } from 'expo-router';
import * as WebBrowser from 'expo-web-browser';
import { useState } from 'react';
import { Pressable, ScrollView, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { useInsights } from '@/api/hooks';
import type { Insight, InsightClaim } from '@/api/types';
import { Glyph } from '@/components/Glyph';
import { InsightActions, insightMeta, noScenariosCopy, ScenarioRow, sortedScenarios, WhatYouCanDo } from '@/components/insights/InsightCard';
import { Txt } from '@/components/Txt';
import { CardSkeleton, EmptyState, SectionTitle, TopBar } from '@/components/ui';
import { topicLabel } from '@/lib/labels';
import { ageLabel } from '@/lib/time';
import { radius, space } from '@/theme/tokens';
import { useTheme } from '@/theme/useTheme';

// "[1, 3]": the claim's sources, numbered as in the source list below
function Cites({ claim, i }: { claim: InsightClaim; i: Insight }) {
  const n = claim.sources.map((a) => i.sources.findIndex((s) => s.article_id === a) + 1).filter((x) => x > 0);
  if (!n.length) return null;
  return <Txt v="meta" muted accessibilityLabel={`Sources ${n.join(', ')}`}> [{n.join(', ')}]</Txt>;
}

export default function InsightScreen() {
  const { c } = useTheme();
  const insets = useSafeAreaInsets();
  const { id } = useLocalSearchParams<{ id: string }>();
  const q = useInsights();
  const i = q.data?.insights.find((x) => x.story_id === id);
  const [open, setOpen] = useState<number | null>(0);

  return (
    <View style={{ flex: 1, backgroundColor: c.bg, paddingTop: insets.top }}>
      <TopBar title="Insight" />
      <ScrollView contentContainerStyle={{ padding: space.gutter, paddingBottom: insets.bottom + space.xxl, maxWidth: 720, width: '100%', alignSelf: 'center' }}>
        {q.isLoading && <CardSkeleton />}
        {!q.isLoading && !i && (
          <EmptyState text="This story is no longer among the developing stories." action="Back to Insights" onAction={() => router.back()} />
        )}
        {i && (
          <>
            <Txt v="label" muted>{topicLabel(i.topic).toUpperCase()} · {insightMeta(i).toUpperCase()}</Txt>
            <Txt v="storyHeadline" accessibilityRole="header" style={{ marginTop: space.sm }}>{i.title}</Txt>
            {i.watch.changed && (
              <View style={{ marginTop: space.sm, alignSelf: 'flex-start', backgroundColor: c.highlight, borderRadius: radius.badge, paddingHorizontal: 8, paddingVertical: 2 }}>
                <Txt v="label" color={c.onHighlight}>Changed since you started watching</Txt>
              </View>
            )}

            <SectionTitle title="What happened" />
            <Txt v="storySummary">{i.what_happened.text}<Cites claim={i.what_happened} i={i} /></Txt>

            {(i.for_you || i.why_it_matters.length > 0) && <SectionTitle title="Why it matters" />}
            {i.for_you && (
              <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8, marginBottom: space.sm }}>
                <Glyph name={i.for_you.kind === 'direct' ? 'person' : 'link'} size={16} color={c.highlight} />
                <Txt v="why" style={{ flex: 1 }}>{i.for_you.text}</Txt>
              </View>
            )}
            {i.why_it_matters.map((w) => (
              <View key={w.text} style={{ flexDirection: 'row', gap: 8, marginBottom: 6 }}>
                <Txt v="body" muted>•</Txt>
                <Txt v="body" style={{ flex: 1 }}>{w.text}<Cites claim={w} i={i} /></Txt>
              </View>
            ))}

            <SectionTitle title="Possible outcomes" sub="AI analysis of the sources. Labels show likelihood, not odds." />
            {i.scenarios.length > 0 ? (
              <View style={{ backgroundColor: c.surface, borderRadius: radius.card, paddingHorizontal: space.md, borderWidth: 1, borderColor: c.hairline }}>
                {sortedScenarios(i.scenarios).map((s, n, all) => (
                  <ScenarioRow key={s.title} s={s} open={open === n} onToggle={() => setOpen(open === n ? null : n)} last={n === all.length - 1} />
                ))}
              </View>
            ) : (
              <Txt v="body" muted>{noScenariosCopy(i)}</Txt>
            )}

            {i.watch_next.length > 0 && (
              <>
                <SectionTitle title="What to watch next" sub="Upcoming events the sources mention" />
                {i.watch_next.map((w) => (
                  <View key={w.text} style={{ flexDirection: 'row', gap: 10, alignItems: 'flex-start', paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: c.hairline }}>
                    <Glyph name="compass" size={16} color={c.ink} />
                    <View style={{ flex: 1 }}>
                      <Txt v="body">{w.text}<Cites claim={w} i={i} /></Txt>
                      {w.when && <Txt v="metaBold" muted>{w.when}</Txt>}
                    </View>
                  </View>
                ))}
              </>
            )}

            {i.actions.length > 0 && (
              <>
                <SectionTitle title="What you can do" sub="Practical steps if this story affects you" />
                <WhatYouCanDo i={i} boxed={false} />
              </>
            )}

            <SectionTitle title="Keep track" />
            <InsightActions i={i} />

            <SectionTitle title={`Sources (${i.source_count})`} sub="Every claim above cites these articles"
              right={<Pressable onPress={() => router.push({ pathname: '/sources/[id]', params: { id: i.lead_article_id } })} hitSlop={8}><Txt v="metaBold">See all</Txt></Pressable>} />
            {i.sources.map((s, n) => (
              <Pressable key={s.article_id} accessibilityRole="link" onPress={() => s.url && void WebBrowser.openBrowserAsync(s.url)}
                style={({ pressed }) => ({ flexDirection: 'row', gap: 10, paddingVertical: 10, borderBottomWidth: 1, borderBottomColor: c.hairline, opacity: pressed ? 0.7 : 1 })}>
                <Txt v="metaBold" muted style={{ width: 20 }}>{n + 1}</Txt>
                <View style={{ flex: 1, gap: 2 }}>
                  <Txt v="metaBold">{s.source_name ?? 'Source'}{ageLabel(s.published_at) ? <Txt v="meta" muted>  {ageLabel(s.published_at)}</Txt> : null}</Txt>
                  <Txt v="body" numberOfLines={2}>{s.title}</Txt>
                </View>
              </Pressable>
            ))}
            <Txt v="meta" muted style={{ marginTop: space.lg }}>
              {i.analysis.status === 'ok'
                ? 'Written by AI from the sources above and checked against them: claims that brought in names, numbers or dates the sources lack were removed. It is analysis, not a prediction.'
                : 'Shown without AI analysis: this is what the sources report.'}
            </Txt>
          </>
        )}
      </ScrollView>
    </View>
  );
}
