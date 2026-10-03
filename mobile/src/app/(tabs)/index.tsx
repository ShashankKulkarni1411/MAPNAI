// H1 Home: a finite brief. Need first, then interest, then what's big for everyone; then hand off to Flash.
import { router, useScrollToTop } from 'expo-router';
import { useEffect, useMemo, useRef, useState } from 'react';
import { Pressable, RefreshControl, ScrollView, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { api } from '@/api/endpoints';
import { invalidatePersona, pendingBriefUpdate, useAlerts, useDigest, useHealth, useProfile, useProposals, useTop, useUserId } from '@/api/hooks';
import type { StoryItem } from '@/api/types';
import { Button } from '@/components/Button';
import { Glyph, SignalBars } from '@/components/Glyph';
import { openStory, StoryCard } from '@/components/story/StoryCard';
import { ActionsSheet, WhySheet } from '@/components/story/sheets';
import { Txt } from '@/components/Txt';
import { Banner, CardSkeleton, EmptyState, InlineError, SectionTitle } from '@/components/ui';
import { clockLabel, dayLabel, greeting, hoursSince, isoDate } from '@/lib/time';
import { react, useFeedback } from '@/state/feedback';
import { usePrefs } from '@/state/prefs';
import { useSession } from '@/state/session';
import { radius, space } from '@/theme/tokens';
import { useTheme } from '@/theme/useTheme';

export default function Home() {
  const { c } = useTheme();
  const insets = useSafeAreaInsets();
  const uid = useUserId();
  const name = useSession((s) => s.name);
  const lastSeenAt = useSession((s) => s.lastSeenAt);
  const setSession = useSession((s) => s.set);
  const digest = useDigest();
  const profile = useProfile();
  const alerts = useAlerts();
  const proposals = useProposals();
  const top = useTop(24);
  const health = useHealth();
  const hidden = useFeedback((s) => (s.hiddenToday.day === isoDate() ? s.hiddenToday.keys : []));
  const seenTips = usePrefs((s) => s.seenTips);
  const markTip = usePrefs((s) => s.markTip);
  const showToast = useFeedback((s) => s.showToast);
  const [refreshing, setRefreshing] = useState(false);
  const [moreOpen, setMoreOpen] = useState(false);
  const [why, setWhy] = useState<StoryItem | null>(null);
  const [actions, setActions] = useState<StoryItem | null>(null);
  const scrollRef = useRef<ScrollView>(null);
  useScrollToTop(scrollRef);

  // Catch-up card when away 48+ hours (computed once per launch), then stamp the visit
  const [awayHours] = useState(() => hoursSince(lastSeenAt));
  useEffect(() => {
    setSession({ lastSeenAt: new Date().toISOString() });
    if (pendingBriefUpdate.flag) {
      pendingBriefUpdate.flag = false;
      showToast('Your brief was updated');
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const keep = (i: StoryItem) => !hidden.includes(`${i.topic}|${i.entities?.[0]?.key ?? ''}`);
  const items = (digest.data?.items ?? []).filter(keep);
  const must = items.filter((i) => i.section === 'must_know');
  const forYou = items.filter((i) => i.section === 'interest');
  const explore = items.find((i) => i.section === 'explore');
  const more = (digest.data?.more_you_need ?? []).filter(keep);
  const shown = useMemo(() => new Set([...items, ...more].map((i) => i.article_id)), [items, more]);
  const big = (top.data ?? []).filter((i) => !shown.has(i.article_id)).slice(0, 5);
  const recentAlerts = (alerts.data ?? []).filter((a) => hoursSince(a.created_at) <= 12).slice(0, 2);
  const follows = profile.data?.exposures ?? [];
  const proposal = proposals.data?.[0];
  const badge = (alerts.data?.length ?? 0) + (proposals.data?.length ?? 0);
  const engineDown = health.data ? !health.data.ok : false;
  const coldStart = profile.data?.created_at ? hoursSince(profile.data.created_at) < 72 : false;

  async function onRefresh() {
    setRefreshing(true);
    try {
      await digest.refresh();
      await Promise.all([alerts.refetch(), proposals.refetch(), top.refetch()]);
    } finally {
      setRefreshing(false);
    }
  }

  async function decide(accept: boolean) {
    if (!proposal) return;
    await api.decideProposal(uid, proposal.proposal_id, accept).catch(() => {});
    if (accept) {
      invalidatePersona();
      showToast(`Following ${proposal.entity_name} · Interested`);
    } else void proposals.refetch();
  }

  const contextLine = [
    must.length ? `${must.length} must-know${must.length === 1 ? '' : 's'} about what you follow` : null,
    recentAlerts.length ? `${recentAlerts.length} alert${recentAlerts.length === 1 ? '' : 's'}` : null,
  ].filter(Boolean).join(' · ');

  return (
    <View style={{ flex: 1, backgroundColor: c.bg }}>
      {engineDown && <View style={{ paddingTop: insets.top }}><Banner text="Personalization is temporarily unavailable" /></View>}
      <ScrollView
        ref={scrollRef}
        contentContainerStyle={{ paddingTop: engineDown ? space.md : insets.top + space.md, paddingHorizontal: space.gutter, paddingBottom: space.xxl * 2, maxWidth: 720, width: '100%', alignSelf: 'center' }}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={c.ink} />}
      >
        {/* 1 Header */}
        <View style={{ flexDirection: 'row', alignItems: 'flex-start' }}>
          <View style={{ flex: 1 }}>
            <Txt v="screenTitle" accessibilityRole="header">Today</Txt>
            <Txt v="meta" muted>{dayLabel()}, {greeting().toLowerCase()}{name ? ` ${name}` : ''}</Txt>
          </View>
          <Pressable onPress={() => router.push('/notifications')} accessibilityRole="button"
            accessibilityLabel={`Notifications${badge ? `, ${badge} new` : ''}`}
            style={{ width: 44, height: 44, alignItems: 'center', justifyContent: 'center' }}>
            <Glyph name="bell" size={24} color={c.ink} />
            {badge > 0 && (
              <View style={{ position: 'absolute', top: 6, right: 6, minWidth: 16, height: 16, borderRadius: 8, backgroundColor: c.impact, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 3 }}>
                <Txt v="label" color="#fff" style={{ fontSize: 10, lineHeight: 12 }}>
                  {Math.min(9, (alerts.data?.length ?? 0) + (proposals.data?.length ?? 0)) === 9 ? '9+' : (alerts.data?.length ?? 0) + (proposals.data?.length ?? 0)}
                </Txt>
              </View>
            )}
          </Pressable>
        </View>
        <Pressable onPress={() => router.push('/search')} accessibilityRole="search" accessibilityLabel="Search teams, players, films"
          style={{ marginTop: space.md, minHeight: 48, borderRadius: radius.button, borderWidth: 1.5, borderColor: c.hairline, backgroundColor: c.surface, flexDirection: 'row', alignItems: 'center', gap: 8, paddingHorizontal: 14 }}>
          <Glyph name="search" color={c.ink2} />
          <Txt v="body" muted>Search teams, players, films</Txt>
        </Pressable>

        {/* 2 Context line */}
        {!!contextLine && <Txt v="meta" style={{ marginTop: space.md }}>{contextLine}</Txt>}

        {/* 3 Alert banner */}
        {recentAlerts.map((a) => (
          <Pressable key={a.alert_id} onPress={() => router.push({ pathname: '/story/[id]', params: { id: a.article_id, ctx: 'alert', note: a.explanation } })}
            accessibilityRole="button" style={{ marginTop: space.sm, borderRadius: radius.card, backgroundColor: c.surface, borderLeftWidth: 4, borderLeftColor: a.tier === 'major' ? c.impact : c.highlight, padding: space.md, gap: 2 }}>
            <Txt v="metaBold" numberOfLines={1}>{a.entity_name}: {a.title}</Txt>
            <Txt v="meta" muted numberOfLines={1}>{a.explanation}</Txt>
          </Pressable>
        ))}
        {recentAlerts.length > 0 && <Button label="See all" variant="text" small onPress={() => router.push('/notifications')} style={{ alignSelf: 'flex-start' }} />}

        {/* 4 Catch-up card (recap builder is Proposed; R1 lands next phase) */}
        {awayHours >= 48 && awayHours !== Infinity && (
          <View style={{ marginTop: space.md, padding: space.lg, borderRadius: radius.card, backgroundColor: c.surface2, gap: 4 }}>
            <Txt v="cardHeadline">You were away {Math.round(awayHours / 24)} days.</Txt>
            <Txt v="meta" muted>Your must-knows below cover what you missed.</Txt>
          </View>
        )}

        {/* 5 Your world */}
        <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ marginTop: space.lg }} contentContainerStyle={{ gap: 14 }}>
          {follows.map((f) => (
            <Pressable key={f.key} onPress={() => router.push({ pathname: '/entity/[key]', params: { key: f.key } })} accessibilityRole="button" accessibilityLabel={f.name}
              style={{ alignItems: 'center', width: 64, gap: 4 }}>
              <View style={{ width: 52, height: 52, borderRadius: 26, borderWidth: 1.5, borderColor: c.hairline, backgroundColor: c.surface, alignItems: 'center', justifyContent: 'center' }}>
                <Txt v="metaBold">{f.name.split(/\s+/).map((w) => w[0]).join('').slice(0, 3).toUpperCase()}</Txt>
              </View>
              <Txt v="label" numberOfLines={1}>{f.name}</Txt>
              <SignalBars level={f.weight} color={c.ink} dim={c.hairline} />
            </Pressable>
          ))}
          <Pressable onPress={() => router.push('/profile/add-follows')} accessibilityRole="button" accessibilityLabel="Follow something"
            style={{ alignItems: 'center', width: 64, gap: 4 }}>
            <View style={{ width: 52, height: 52, borderRadius: 26, borderWidth: 1.5, borderStyle: 'dashed', borderColor: c.ink2, alignItems: 'center', justifyContent: 'center' }}>
              <Glyph name="plus" color={c.ink} />
            </View>
            <Txt v="label">Follow</Txt>
          </Pressable>
        </ScrollView>

        {digest.isError && !digest.data && <View style={{ marginTop: space.lg }}><InlineError text="Couldn't refresh your brief." onRetry={() => digest.refetch()} /></View>}
        {digest.isError && digest.data && <View style={{ marginTop: space.lg }}><InlineError text="Couldn't refresh · showing your last brief." onRetry={onRefresh} /></View>}

        {/* 6 Must know */}
        <SectionTitle title="Must know" />
        {!seenTips.mustKnow && digest.data && (
          <Pressable onPress={() => markTip('mustKnow')} accessibilityRole="button" accessibilityHint="Dismiss tip"
            style={{ padding: space.md, borderRadius: radius.card, backgroundColor: c.ink, marginBottom: space.md }}>
            <Txt v="meta" color={c.bg}>Stories about what you follow, ranked by how big they are. Every story says why it’s here. Tap to dismiss.</Txt>
          </Pressable>
        )}
        {digest.isLoading && !digest.data && (<><CardSkeleton /><CardSkeleton /><CardSkeleton /></>)}
        {digest.data && must.length === 0 && (
          follows.length === 0
            ? <EmptyState text="Follow teams, players or films to get must-know stories." action="Follow" onAction={() => router.push('/profile/add-follows')} />
            : <EmptyState text="Nothing urgent about what you follow right now." />
        )}
        {must.map((i, n) => (
          <StoryCard key={i.article_id} item={i} variant={n === 0 ? 'hero' : 'standard'} onWhy={setWhy} onActions={setActions} />
        ))}

        {/* 7 More you may need */}
        {more.length > 0 && (
          <View style={{ borderRadius: radius.card, borderWidth: 1, borderColor: c.hairline, backgroundColor: c.surface, marginBottom: space.md }}>
            <Pressable onPress={() => setMoreOpen((o) => !o)} accessibilityRole="button" accessibilityState={{ expanded: moreOpen }}
              style={{ flexDirection: 'row', alignItems: 'center', padding: space.lg, minHeight: 52 }}>
              <Txt v="metaBold" style={{ flex: 1 }}>{more.length} more you may need</Txt>
              <Txt v="meta" muted>{moreOpen ? 'Hide' : 'Show'}</Txt>
            </Pressable>
            {moreOpen && <View style={{ paddingHorizontal: space.md }}>{more.map((i) => <StoryCard key={i.article_id} item={i} variant="compact" onWhy={setWhy} onActions={setActions} />)}</View>}
          </View>
        )}

        {/* 8 For you */}
        {forYou.length > 0 && (
          <>
            <SectionTitle title="For you" sub={coldStart ? 'Your brief gets sharper as you read.' : undefined} />
            {forYou.map((i) => <StoryCard key={i.article_id} item={i} onWhy={setWhy} onActions={setActions} />)}
          </>
        )}

        {/* 9 New for you */}
        {explore && (
          <View>
            <StoryCard item={explore} onWhy={setWhy} onActions={setActions} />
            <View style={{ flexDirection: 'row', gap: 8, marginTop: -space.sm, marginBottom: space.md }}>
              <Button label="More of this" variant="secondary" small onPress={() => react(explore.article_id, 'more')} />
              <Button label="Not for me" variant="secondary" small onPress={() => react(explore.article_id, 'less')} />
            </View>
          </View>
        )}

        {/* 10 Big today */}
        {big.length > 0 && (
          <>
            <SectionTitle title="Big today" sub="Most covered, whatever you follow" />
            <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: space.md }}>
              {big.map((i) => (
                <Pressable key={i.article_id} onPress={() => openStory(i)} accessibilityRole="button"
                  style={{ width: 220, padding: space.md, borderRadius: radius.card, borderWidth: 1, borderColor: c.hairline, backgroundColor: c.surface, gap: 8 }}>
                  <Txt v="compactHeadline" numberOfLines={3}>{i.title}</Txt>
                  <View style={{ flexDirection: 'row', alignItems: 'center', gap: 4 }}>
                    <Glyph name="stack" size={14} color={c.ink2} />
                    <Txt v="meta" muted tabular>{i.cluster_size} sources</Txt>
                  </View>
                </Pressable>
              ))}
            </ScrollView>
          </>
        )}

        {/* 11 Suggestion */}
        {proposal && (
          <View style={{ marginTop: space.xxl, padding: space.lg, borderRadius: radius.card, backgroundColor: c.surface2, gap: space.sm }}>
            <Txt v="cardHeadline">Follow {proposal.entity_name}?</Txt>
            <Txt v="meta" muted>{proposal.reason}</Txt>
            <View style={{ flexDirection: 'row', gap: 8, flexWrap: 'wrap' }}>
              <Button label="Follow" small onPress={() => decide(true)} />
              <Button label="Not now" variant="secondary" small onPress={() => decide(false)} />
              <Button label="See why" variant="text" small onPress={() => router.push('/profile/suggestions')} />
            </View>
          </View>
        )}

        {/* 12 End of brief */}
        {digest.data && (
          <View style={{ marginTop: space.xxl, gap: space.md, alignItems: 'stretch' }}>
            <Txt v="meta" muted style={{ textAlign: 'center' }}>You’re up to date · Updated {clockLabel(digest.data.generated_at)}</Txt>
            <Button label="Keep going in Flash" onPress={() => router.navigate('/(tabs)/flash')} />
            <Button label="Refresh" variant="text" onPress={onRefresh} />
          </View>
        )}
      </ScrollView>
      <WhySheet item={why} onClose={() => setWhy(null)} />
      <ActionsSheet item={actions} onClose={() => setActions(null)} onWhy={setWhy} />
    </View>
  );
}
