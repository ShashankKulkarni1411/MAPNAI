// I2 Insight card: a developing story, what it means and what could happen next. Collapsed it stays scannable
// (what happened, your link to it, the outcomes by likelihood, what you can do); a scenario opens for its explanation
// and signals.
// Scenarios are AI analysis of the cited sources, labelled by likelihood only, never a percentage.
import { router } from 'expo-router';
import { useState } from 'react';
import { Pressable, View } from 'react-native';

import { useFollow, useProfile, useWatchInsight } from '@/api/hooks';
import type { Insight, InsightScenario, Likelihood } from '@/api/types';
import { topicLabel } from '@/lib/labels';
import { ageLabel } from '@/lib/time';
import { useFeedback } from '@/state/feedback';
import { radius, space } from '@/theme/tokens';
import { useTheme } from '@/theme/useTheme';
import { Glyph, topicGlyph } from '../Glyph';
import { Txt } from '../Txt';
import { Chip } from '../ui';

export const LIKELIHOOD_LABEL: Record<Likelihood, string> = { likely: 'Likely', possible: 'Possible', unlikely: 'Unlikely' };
const LIKELIHOOD_ORDER: Record<Likelihood, number> = { likely: 0, possible: 1, unlikely: 2 };

export function sortedScenarios(s: InsightScenario[]): InsightScenario[] {
  return [...s].sort((a, b) => LIKELIHOOD_ORDER[a.likelihood] - LIKELIHOOD_ORDER[b.likelihood]);
}

// "Developing · 12 sources · 2 days"
export function insightMeta(i: Insight): string {
  const days = i.span_days > 1 ? ` · ${i.span_days} days` : '';
  const updated = ageLabel(i.last_updated);
  return `Developing · ${i.source_count} sources${days}${updated ? ` · updated ${updated}` : ''}`;
}

// Why there are no scenarios, in plain words
export function noScenariosCopy(i: Insight): string | null {
  if (i.scenarios.length) return null;
  if (i.analysis.status === 'partial') return "Possible outcomes didn't pass our check against the sources, so none are shown.";
  return 'AI analysis is unavailable right now. This is what the sources report.';
}

export function openInsight(i: Insight) {
  router.push({ pathname: '/insight/[id]', params: { id: i.story_id } });
}

export function LikelihoodChip({ value }: { value: Likelihood }) {
  const { c } = useTheme();
  const filled = value === 'likely';
  return (
    <View accessibilityLabel={`${LIKELIHOOD_LABEL[value]} outcome`}
      style={{ paddingHorizontal: 8, paddingVertical: 2, borderRadius: radius.badge, borderWidth: 1.5, minWidth: 70, alignItems: 'center',
        borderColor: value === 'unlikely' ? c.hairline : c.ink, backgroundColor: filled ? c.ink : 'transparent' }}>
      <Txt v="label" color={filled ? c.bg : value === 'unlikely' ? c.ink2 : c.ink}>{LIKELIHOOD_LABEL[value]}</Txt>
    </View>
  );
}

export function ScenarioRow({ s, open, onToggle, last }: { s: InsightScenario; open: boolean; onToggle: () => void; last?: boolean }) {
  const { c } = useTheme();
  return (
    <View style={{ borderBottomWidth: last ? 0 : 1, borderBottomColor: c.hairline }}>
      <Pressable onPress={onToggle} accessibilityRole="button" accessibilityState={{ expanded: open }}
        accessibilityLabel={`${LIKELIHOOD_LABEL[s.likelihood]}: ${s.title}`} accessibilityHint={open ? 'Hides the details' : 'Shows what to watch for'}
        style={({ pressed }) => ({ flexDirection: 'row', alignItems: 'center', gap: 10, minHeight: 44, paddingVertical: 6, opacity: pressed ? 0.7 : 1 })}>
        <LikelihoodChip value={s.likelihood} />
        <Txt v="metaBold" style={{ flex: 1 }}>{s.title}</Txt>
        <View style={{ transform: [{ rotate: open ? '90deg' : '0deg' }] }}>
          <Glyph name="chevron" size={16} color={c.ink2} />
        </View>
      </Pressable>
      {open && (
        <View style={{ paddingBottom: space.md, paddingLeft: 80, gap: 6 }}>
          <Txt v="body">{s.explanation}</Txt>
          {s.watch_for.length > 0 && (
            <View style={{ gap: 2 }}>
              <Txt v="label" muted>WATCH FOR</Txt>
              {s.watch_for.map((w) => (
                <View key={w} style={{ flexDirection: 'row', gap: 6 }}>
                  <Txt v="meta" muted>•</Txt>
                  <Txt v="meta" style={{ flex: 1 }}>{w}</Txt>
                </View>
              ))}
            </View>
          )}
          <Txt v="meta" muted>Based on {s.sources.length} {s.sources.length === 1 ? 'source' : 'sources'}</Txt>
        </View>
      )}
    </View>
  );
}

// Practical steps for readers the story affects (from the analysis, or Agent 4's recommendation without one)
export function WhatYouCanDo({ i, boxed = true }: { i: Insight; boxed?: boolean }) {
  const { c } = useTheme();
  if (!i.actions.length) return null;
  const fromRisk = i.actions.every((a) => a.origin === 'risk_agent');
  return (
    <View style={[{ gap: 6 }, boxed && { borderLeftWidth: 3, borderLeftColor: c.highlight, paddingLeft: space.md }]}>
      {boxed && <Txt v="label" muted>WHAT YOU CAN DO</Txt>}
      {i.actions.map((a) => (
        <View key={a.text} style={{ flexDirection: 'row', gap: 8, alignItems: 'flex-start' }}>
          <View style={{ marginTop: 2 }}><Glyph name="check" size={15} color={c.highlight} /></View>
          <Txt v="body" style={{ flex: 1 }}>{a.text}</Txt>
        </View>
      ))}
      {fromRisk && <Txt v="meta" muted>From our risk check of the lead article.</Txt>}
    </View>
  );
}

// Follow / Alert me / Ask a follow-up / Sources
export function InsightActions({ i, compact }: { i: Insight; compact?: boolean }) {
  const { c } = useTheme();
  const follow = useFollow();
  const watch = useWatchInsight();
  const profile = useProfile();
  const showToast = useFeedback((s) => s.showToast);
  const followedNow = new Set(profile.data?.exposures.map((e) => e.key) ?? []);
  const toFollow = i.entities.filter((e) => !e.followed && !followedNow.has(e.key)).slice(0, compact ? 2 : 4);
  const watching = i.watch.watching;

  const doFollow = (key: string, name: string) =>
    follow.mutate({ upsert: [{ key, role: 'follows', weight: 2 }] }, {
      onSuccess: () => showToast(`Following ${name} · Important`, () => follow.mutate({ remove: [key] })),
      onError: () => showToast(`Couldn't follow ${name}. Try again.`),
    });
  const doWatch = () =>
    watch.mutate({ story_id: i.story_id, on: !watching }, {
      onSuccess: () => showToast(watching ? 'Stopped watching this story' : "We'll flag this story here when it changes"),
      onError: () => showToast("Couldn't update. Try again."),
    });
  const ask = () =>
    router.push({ pathname: '/ask', params: { article: i.lead_article_id, title: i.title, q: `What happens next with ${i.entities[0]?.name ?? 'this story'}?` } });

  return (
    <View style={{ gap: space.sm }}>
      {toFollow.length > 0 && (
        <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 6 }}>
          {toFollow.map((e) => (
            <Chip key={e.key} small icon="plus" label={e.name} accessibilityHint={`Follows ${e.name}`} onPress={() => doFollow(e.key, e.name)} />
          ))}
        </View>
      )}
      <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 6 }}>
        <Chip icon="bell" label={watching ? 'Watching' : 'Alert me if this changes'} selected={watching} onPress={doWatch}
          accessibilityHint={watching ? 'Stops watching this story' : 'Marks this story when it gets new sources or a new analysis'} />
        <Chip icon="ask" label="Ask a follow-up" onPress={ask} />
        <Chip icon="stack" label="Sources" onPress={() => router.push({ pathname: '/sources/[id]', params: { id: i.lead_article_id } })} />
      </View>
      {watching && (
        <Txt v="meta" muted>
          Watching{i.watch.since ? ` since ${new Date(i.watch.since).toLocaleDateString(undefined, { day: 'numeric', month: 'short' })}` : ''}
          {i.watch.new_sources ? ` · ${i.watch.new_sources} new ${i.watch.new_sources === 1 ? 'source' : 'sources'}` : ' · no new sources yet'}
        </Txt>
      )}
      <View style={{ height: 1 }} />
      <Txt v="meta" color={c.ink2}>{i.disclaimer}</Txt>
    </View>
  );
}

export function InsightCard({ i }: { i: Insight }) {
  const { c } = useTheme();
  const [open, setOpen] = useState<number | null>(null);
  const scenarios = sortedScenarios(i.scenarios);
  const empty = noScenariosCopy(i);
  const topicColor = i.topic === 'sports' ? c.sports : i.topic === 'entertainment_movies' ? c.film : c.general;

  return (
    <View style={{ backgroundColor: c.surface, borderRadius: radius.card, padding: space.lg, gap: space.md, marginBottom: space.md, borderWidth: 1, borderColor: c.hairline }}>
      <Pressable onPress={() => openInsight(i)} accessibilityRole="button" accessibilityLabel={`${i.title}. ${i.what_happened.text}`}
        accessibilityHint="Opens the full analysis" style={({ pressed }) => ({ gap: 6, opacity: pressed ? 0.8 : 1 })}>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
          <Glyph name={topicGlyph(i.topic)} size={14} color={topicColor} />
          <Txt v="label" color={topicColor}>{topicLabel(i.topic).toUpperCase()}</Txt>
          <Txt v="meta" muted style={{ flex: 1 }} numberOfLines={1}>{insightMeta(i)}</Txt>
          {i.watch.changed && (
            <View style={{ backgroundColor: c.highlight, borderRadius: radius.badge, paddingHorizontal: 6, paddingVertical: 1 }}>
              <Txt v="label" color={c.onHighlight}>Changed</Txt>
            </View>
          )}
        </View>
        <Txt v="cardHeadline">{i.title}</Txt>
        <Txt v="body" numberOfLines={3}>{i.what_happened.text}</Txt>
        {i.for_you && (
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
            <Glyph name={i.for_you.kind === 'direct' ? 'person' : 'link'} size={15} color={c.highlight} />
            <Txt v="why" style={{ flex: 1 }}>{i.for_you.text}</Txt>
          </View>
        )}
        {!i.for_you && i.why_it_matters[0] && <Txt v="meta" muted numberOfLines={2}>Why it matters: {i.why_it_matters[0].text}</Txt>}
      </Pressable>

      {scenarios.length > 0 ? (
        <View>
          <Txt v="label" muted>POSSIBLE OUTCOMES · AI ANALYSIS</Txt>
          {scenarios.map((s, n) => (
            <ScenarioRow key={s.title} s={s} open={open === n} onToggle={() => setOpen(open === n ? null : n)} last={n === scenarios.length - 1} />
          ))}
        </View>
      ) : (
        empty && <Txt v="meta" muted>{empty}</Txt>
      )}

      <WhatYouCanDo i={i} />

      {i.watch_next[0] && (
        <View style={{ flexDirection: 'row', gap: 8, alignItems: 'center', backgroundColor: c.surface2, borderRadius: radius.button, padding: space.sm }}>
          <Glyph name="compass" size={15} color={c.ink} />
          <Txt v="meta" style={{ flex: 1 }}>
            <Txt v="metaBold">Next: </Txt>{i.watch_next[0].text}{i.watch_next[0].when ? ` · ${i.watch_next[0].when}` : ''}
          </Txt>
        </View>
      )}

      <InsightActions i={i} compact />
      <Pressable onPress={() => openInsight(i)} accessibilityRole="button" hitSlop={8}
        style={{ flexDirection: 'row', alignItems: 'center', alignSelf: 'flex-start', gap: 4, minHeight: 32 }}>
        <Txt v="metaBold">Full analysis</Txt>
        <Glyph name="chevron" size={14} color={c.ink} />
      </Pressable>
    </View>
  );
}
