// F1 Flash: one story per screen. Must know first, then For you / New for you, then every overflow item,
// then the "caught up" divider, then ranked continuation pages (Proposed /feed). Night-navy by default.
import { useInfiniteQuery } from '@tanstack/react-query';
import { router, useScrollToTop } from 'expo-router';
import { useCallback, useMemo, useRef, useState } from 'react';
import { FlatList, LayoutChangeEvent, Pressable, Share, View, ViewToken } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { api } from '@/api/endpoints';
import { useDigest, useTop, useUserId } from '@/api/hooks';
import type { StoryItem } from '@/api/types';
import { Button } from '@/components/Button';
import { Glyph } from '@/components/Glyph';
import { Badges, MetaLine, openStory, summaryOf } from '@/components/story/StoryCard';
import { ActionsSheet, WhySheet } from '@/components/story/sheets';
import { WhyLine } from '@/components/story/why';
import { Txt } from '@/components/Txt';
import { Chip } from '@/components/ui';
import { sectionLabel } from '@/lib/labels';
import { implicit, react, toggleSave, useFeedback } from '@/state/feedback';
import { usePrefs } from '@/state/prefs';
import { radius, space } from '@/theme/tokens';
import { ForceDarkProvider, useTheme } from '@/theme/useTheme';

type Row =
  | { kind: 'story'; item: StoryItem; brief: boolean }
  | { kind: 'divider'; counts: { must: number; forYou: number; explore: number } }
  | { kind: 'end' }
  | { kind: 'loading' };

export default function Flash() {
  const flashDark = usePrefs((s) => s.flashAlwaysDark);
  const { c } = useTheme({ forceDark: flashDark });
  const insets = useSafeAreaInsets();
  const uid = useUserId();
  const digest = useDigest();
  const top = useTop(24);
  const [h, setH] = useState(0);
  const [index, setIndex] = useState(0);
  const [why, setWhy] = useState<StoryItem | null>(null);
  const [actions, setActions] = useState<StoryItem | null>(null);
  const [hintSeen, setHintSeen] = useState(false);
  const listRef = useRef<FlatList<Row>>(null);
  useScrollToTop(listRef);

  // Brief in feed order
  const brief = useMemo(() => {
    const d = digest.data;
    if (!d) return [] as StoryItem[];
    const must = d.items.filter((i) => i.section === 'must_know');
    const rest = d.items.filter((i) => i.section !== 'must_know').sort((a, b) => (a.slot ?? 0) - (b.slot ?? 0));
    return [...must, ...rest, ...d.more_you_need];
  }, [digest.data]);

  const briefIds = useMemo(() => brief.map((i) => i.article_id), [brief]);
  const feed = useInfiniteQuery({
    queryKey: ['feed', uid, briefIds.join(',')],
    enabled: !!uid && !!digest.data,
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) => api.feed(uid, pageParam, briefIds),
    getNextPageParam: (last) => (last.exhausted ? undefined : last.next_cursor),
  });

  const rows: Row[] = useMemo(() => {
    const out: Row[] = brief.map((item) => ({ kind: 'story', item, brief: true }));
    if (!digest.data) return out;
    out.push({
      kind: 'divider',
      counts: {
        must: brief.filter((i) => i.section === 'must_know').length,
        forYou: brief.filter((i) => i.section === 'interest').length,
        explore: brief.filter((i) => i.section === 'explore').length,
      },
    });
    const seen = new Set(briefIds);
    const bigQueue = (top.data ?? []).filter((i) => !seen.has(i.article_id));
    (feed.data?.pages ?? []).forEach((p) => {
      p.items.forEach((item) => {
        if (seen.has(item.article_id)) return;
        seen.add(item.article_id);
        out.push({ kind: 'story', item, brief: false });
      });
      // one Big today item per page, labelled as outside your usual
      const b = bigQueue.find((x) => !seen.has(x.article_id));
      if (b) {
        seen.add(b.article_id);
        out.push({ kind: 'story', item: { ...b, section: 'big_today' }, brief: false });
      }
    });
    out.push(feed.hasNextPage || feed.isFetching ? { kind: 'loading' } : { kind: 'end' });
    return out;
  }, [brief, briefIds, digest.data, feed.data, feed.hasNextPage, feed.isFetching, top.data]);

  // Dwell: active foreground time on a card, capped at 120 s; sent above 15 s
  const shownAt = useRef<{ id: string; t: number } | null>(null);
  const onViewable = useRef(({ viewableItems }: { viewableItems: ViewToken<Row>[] }) => {
    const v = viewableItems[0];
    if (!v) return;
    const prev = shownAt.current;
    if (prev) implicit(prev.id, 'dwell', Math.min(120, (Date.now() - prev.t) / 1000));
    setIndex(v.index ?? 0);
    shownAt.current = v.item.kind === 'story' ? { id: v.item.item.article_id, t: Date.now() } : null;
  }).current;

  const goTo = useCallback((i: number) => {
    if (i >= 0 && i < rows.length) listRef.current?.scrollToIndex({ index: i, animated: true });
  }, [rows.length]);

  const briefCount = brief.length;
  const onLayout = (e: LayoutChangeEvent) => setH(e.nativeEvent.layout.height);

  const renderStory = (item: StoryItem, i: number, inBrief: boolean) => (
    <FlashCard item={item} index={i} total={briefCount} inBrief={inBrief} height={h}
      showHint={i === 0 && !hintSeen}
      onWhy={() => setWhy(item)} onActions={() => setActions(item)}
      onNext={() => goTo(i + 1)} onPrev={() => goTo(i - 1)} forceDark={flashDark} />
  );

  return (
    <ForceDarkProvider value={flashDark}>
    <View style={{ flex: 1, backgroundColor: c.bg, paddingTop: insets.top }} onLayout={onLayout}>
      {h > 0 && (
        <FlatList
          ref={listRef}
          data={rows}
          keyExtractor={(r, i) => (r.kind === 'story' ? r.item.article_id : `${r.kind}-${i}`)}
          pagingEnabled
          showsVerticalScrollIndicator={false}
          decelerationRate="fast"
          snapToInterval={h - insets.top}
          getItemLayout={(_, i) => ({ length: h - insets.top, offset: (h - insets.top) * i, index: i })}
          onViewableItemsChanged={onViewable}
          viewabilityConfig={{ itemVisiblePercentThreshold: 90, minimumViewTime: 1000 }}
          onScrollBeginDrag={() => setHintSeen(true)}
          onEndReached={() => feed.hasNextPage && !feed.isFetchingNextPage && feed.fetchNextPage()}
          onEndReachedThreshold={3}
          windowSize={7}
          ListEmptyComponent={
            <View style={{ height: h - insets.top, alignItems: 'center', justifyContent: 'center', padding: space.xl, gap: space.md }}>
              <Txt v="sectionTitle" color={c.ink}>{digest.isLoading ? 'Loading your brief' : 'No new stories in the last 48 hours'}</Txt>
            </View>
          }
          renderItem={({ item: r, index: i }) => {
            const pageH = h - insets.top;
            if (r.kind === 'story') return renderStory(r.item, i, r.brief);
            if (r.kind === 'divider')
              return (
                <View style={{ height: pageH, justifyContent: 'center', padding: space.gutter }}>
                  <View style={{ backgroundColor: c.surface, borderRadius: radius.card, padding: space.xl, gap: space.sm }}>
                    <Txt v="heroHeadline" color={c.ink}>You’re caught up on what matters today</Txt>
                    <Txt v="meta" color={c.ink2}>
                      {r.counts.must} must-know{r.counts.must === 1 ? '' : 's'}, {r.counts.forYou} for you, {r.counts.explore} new for you
                    </Txt>
                    <Txt v="body" color={c.ink}>Keep swiping for more for you</Txt>
                  </View>
                </View>
              );
            if (r.kind === 'loading')
              return <View style={{ height: pageH, alignItems: 'center', justifyContent: 'center' }}><Txt v="meta" color={c.ink2}>{feed.isError ? 'Couldn’t load more' : 'Loading more…'}</Txt>{feed.isError && <Button label="Retry" variant="secondary" small forceDark onPress={() => feed.fetchNextPage()} />}</View>;
            return (
              <View style={{ height: pageH, alignItems: 'center', justifyContent: 'center', padding: space.xl, gap: space.md }}>
                <Txt v="heroHeadline" color={c.ink} style={{ textAlign: 'center' }}>That’s everything from the past week</Txt>
                <Button label="Search" variant="secondary" forceDark onPress={() => router.push('/search')} />
                <Button label="Back to top" variant="text" forceDark onPress={() => goTo(0)} />
              </View>
            );
          }}
        />
      )}
      {index > 3 && (
        <Pressable onPress={() => goTo(0)} accessibilityRole="button" accessibilityLabel="Back to top"
          style={{ position: 'absolute', top: insets.top + 8, right: space.gutter, backgroundColor: c.surface2, borderRadius: radius.chip, paddingHorizontal: 12, minHeight: 32, justifyContent: 'center' }}>
          <Txt v="label" color={c.ink}>Back to top</Txt>
        </Pressable>
      )}
      <WhySheet item={why} onClose={() => setWhy(null)} />
      <ActionsSheet item={actions} onClose={() => setActions(null)} onWhy={setWhy} />
    </View>
    </ForceDarkProvider>
  );
}

function FlashCard({
  item, index, total, inBrief, height, showHint, onWhy, onActions, onNext, onPrev, forceDark,
}: {
  item: StoryItem; index: number; total: number; inBrief: boolean; height: number; showHint: boolean;
  onWhy: () => void; onActions: () => void; onNext: () => void; onPrev: () => void; forceDark: boolean;
}) {
  const { c } = useTheme({ forceDark });
  const insets = useSafeAreaInsets();
  const reaction = useFeedback((s) => s.reaction[item.article_id]);
  const saved = useFeedback((s) => !!s.saved[item.article_id]);
  const isMust = item.section === 'must_know' || item.section === 'just_in';
  const { text, limited } = summaryOf(item);
  const pageH = height - insets.top;

  const act = (label: string, on: boolean, fn: () => void) => (
    <Pressable onPress={fn} accessibilityRole="button" accessibilityLabel={label} accessibilityState={{ selected: on }}
      style={{ flex: 1, minHeight: 48, borderRadius: radius.button, borderWidth: 1.5, borderColor: on ? c.ink : c.hairline, backgroundColor: on ? c.ink : 'transparent', alignItems: 'center', justifyContent: 'center' }}>
      <Txt v="button" color={on ? c.bg : c.ink}>{label}</Txt>
    </Pressable>
  );

  return (
    <View style={{ height: pageH, paddingHorizontal: space.gutter, paddingTop: space.sm, paddingBottom: space.md, maxWidth: 560, width: '100%', alignSelf: 'center' }}>
      {/* Progress across the brief; after the divider it becomes a plain label */}
      {inBrief ? (
        <View style={{ gap: 6 }} accessibilityLabel={`${index + 1} of ${total}`}>
          <View style={{ flexDirection: 'row', gap: 3 }}>
            {Array.from({ length: total }).map((_, i) => (
              <View key={i} style={{ flex: 1, height: 3, borderRadius: 2, backgroundColor: i <= index ? c.ink : c.hairline }} />
            ))}
          </View>
          <Txt v="label" color={c.ink2} style={{ alignSelf: 'flex-end' }} tabular>{index + 1} of {total}</Txt>
        </View>
      ) : (
        <Txt v="label" color={c.ink2}>{item.section === 'big_today' ? 'Outside your usual: a big story today' : sectionLabel.feed}</Txt>
      )}

      <Pressable
        style={{ flex: 1, marginTop: space.md, gap: space.md, borderLeftWidth: isMust ? 4 : 0, borderLeftColor: c.highlight, paddingLeft: isMust ? space.md : 0 }}
        onPress={() => openStory(item)}
        onLongPress={onActions}
        accessibilityRole="button"
        accessibilityLabel={`${item.section ? sectionLabel[item.section] + '. ' : ''}${item.title}`}
        accessibilityHint="Opens the story"
        accessibilityActions={[
          { name: 'activate', label: 'Open story' },
          { name: 'next', label: 'Next story' },
          { name: 'prev', label: 'Previous story' },
          { name: 'longpress', label: 'Story actions' },
          { name: 'why', label: 'Why this?' },
        ]}
        onAccessibilityAction={(e) => {
          const n = e.nativeEvent.actionName;
          if (n === 'activate') openStory(item);
          if (n === 'next') onNext();
          if (n === 'prev') onPrev();
          if (n === 'longpress') onActions();
          if (n === 'why') onWhy();
        }}
      >
        <Badges item={item} forceDark={forceDark} />
        <MetaLine item={item} forceDark={forceDark} />
        <Txt v="flashHeadline" color={c.ink} numberOfLines={4}>{item.title}</Txt>
        {text && <Txt v="summary" color={c.ink} numberOfLines={7}>{limited ? `${text}…` : text}</Txt>}
        {limited && <Txt v="label" color={c.ink2}>{item.topic === 'other' ? 'Limited analysis' : 'Summary not ready yet'}</Txt>}
        <WhyLine item={item} onPress={onWhy} forceDark={forceDark} />
        {!!item.entities?.length && (
          <View style={{ flexDirection: 'row', gap: 6, flexWrap: 'wrap' }}>
            {item.entities.slice(0, 3).map((e) => (
              <Chip key={e.key} label={e.name} forceDark={forceDark} onPress={() => router.push({ pathname: '/entity/[key]', params: { key: e.key } })} />
            ))}
          </View>
        )}
        <View style={{ flex: 1 }} />
        {showHint && (
          <View style={{ alignSelf: 'center', borderWidth: 1, borderStyle: 'dashed', borderColor: c.ink2, borderRadius: radius.chip, paddingHorizontal: 14, paddingVertical: 6 }}>
            <Txt v="meta" color={c.ink2}>Swipe up for the next story · tap to read · hold for more</Txt>
          </View>
        )}
      </Pressable>

      <View style={{ flexDirection: 'row', gap: 8, marginTop: space.md }}>
        {act('More', reaction === 'more', () => react(item.article_id, 'more'))}
        {act('Less', reaction === 'less', () => react(item.article_id, 'less'))}
        {act(saved ? 'Saved' : 'Save', saved, () => toggleSave(item.article_id))}
        <Pressable onPress={() => void Share.share({ message: `${item.title}\n${item.url}` })} accessibilityRole="button" accessibilityLabel="Share"
          style={{ width: 52, minHeight: 48, borderRadius: radius.button, borderWidth: 1.5, borderColor: c.hairline, alignItems: 'center', justifyContent: 'center' }}>
          <Glyph name="share" color={c.ink} />
        </Pressable>
      </View>
    </View>
  );
}
