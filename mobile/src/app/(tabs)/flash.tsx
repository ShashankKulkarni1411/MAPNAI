// F1 Flash: one story per screen. Must know first, then For you / New for you, then every overflow item,
// then the "caught up" divider, then ranked continuation pages (Proposed /feed). Night-navy by default.
// Each story is full-bleed over its ingested image (components/story/FlashStory); the next images are prefetched.
import { useInfiniteQuery } from '@tanstack/react-query';
import { Image } from 'expo-image';
import { router, useFocusEffect, useScrollToTop } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { FlatList, LayoutChangeEvent, Pressable, View, ViewToken } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { api } from '@/api/endpoints';
import { useDigest, useTop, useUserId } from '@/api/hooks';
import type { StoryItem } from '@/api/types';
import { Button } from '@/components/Button';
import { FlashStory, heroImage } from '@/components/story/FlashStory';
import { ActionsSheet, CommentsSheet, WhySheet } from '@/components/story/sheets';
import { Txt } from '@/components/Txt';
import { hydrate, implicit } from '@/state/feedback';
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
  const { c, isDark } = useTheme({ forceDark: flashDark });
  const insets = useSafeAreaInsets();
  const uid = useUserId();
  const digest = useDigest();
  const top = useTop(24);
  const [h, setH] = useState(0);
  const [index, setIndex] = useState(0);
  const [why, setWhy] = useState<StoryItem | null>(null);
  const [actions, setActions] = useState<StoryItem | null>(null);
  const [comments, setComments] = useState<StoryItem | null>(null);
  const [focused, setFocused] = useState(false);
  useFocusEffect(useCallback(() => { setFocused(true); return () => setFocused(false); }, []));
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

  // Your own like / dislike / save from earlier sessions (the server sends it as `viewer`)
  useEffect(() => {
    hydrate([...brief, ...(feed.data?.pages ?? []).flatMap((p) => p.items)]);
  }, [brief, feed.data]);

  // Swiping should never wait for a picture: keep the current and next two stories' images warm
  useEffect(() => {
    const urls = rows.slice(index, index + 3)
      .map((r) => (r.kind === 'story' ? heroImage(r.item)?.url : undefined))
      .filter((u): u is string => !!u);
    if (urls.length) void Image.prefetch(urls, 'memory-disk').catch(() => {});
  }, [index, rows]);

  const goTo = useCallback((i: number) => {
    if (i >= 0 && i < rows.length) listRef.current?.scrollToIndex({ index: i, animated: true });
  }, [rows.length]);

  const briefCount = brief.length;
  const onLayout = (e: LayoutChangeEvent) => setH(e.nativeEvent.layout.height);

  const renderStory = (item: StoryItem, i: number, inBrief: boolean) => (
    <FlashStory item={item} index={i} total={briefCount} inBrief={inBrief} height={h}
      showHint={i === 0 && !hintSeen}
      onWhy={() => setWhy(item)} onActions={() => setActions(item)} onComments={() => setComments(item)}
      onNext={() => goTo(i + 1)} onPrev={() => goTo(i - 1)} />
  );

  return (
    <ForceDarkProvider value={flashDark}>
    {focused && <StatusBar style={isDark ? 'light' : 'dark'} />}
    <View style={{ flex: 1, backgroundColor: c.bg }} onLayout={onLayout}>
      {h > 0 && (
        <FlatList
          ref={listRef}
          data={rows}
          keyExtractor={(r, i) => (r.kind === 'story' ? r.item.article_id : `${r.kind}-${i}`)}
          pagingEnabled
          showsVerticalScrollIndicator={false}
          decelerationRate="fast"
          snapToInterval={h}
          getItemLayout={(_, i) => ({ length: h, offset: h * i, index: i })}
          onViewableItemsChanged={onViewable}
          viewabilityConfig={{ itemVisiblePercentThreshold: 90, minimumViewTime: 1000 }}
          onScrollBeginDrag={() => setHintSeen(true)}
          onEndReached={() => feed.hasNextPage && !feed.isFetchingNextPage && feed.fetchNextPage()}
          onEndReachedThreshold={3}
          windowSize={7}
          ListEmptyComponent={
            <View style={{ height: h, alignItems: 'center', justifyContent: 'center', padding: space.xl, gap: space.md }}>
              <Txt v="sectionTitle" color={c.ink}>{digest.isLoading ? 'Loading your brief' : 'No new stories in the last 48 hours'}</Txt>
            </View>
          }
          renderItem={({ item: r, index: i }) => {
            const pageH = h;
            if (r.kind === 'story') return renderStory(r.item, i, r.brief);
            if (r.kind === 'divider')
              return (
                <View style={{ height: pageH, justifyContent: 'center', padding: space.gutter, paddingTop: insets.top }}>
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
              return <View style={{ height: pageH, alignItems: 'center', justifyContent: 'center', paddingTop: insets.top }}><Txt v="meta" color={c.ink2}>{feed.isError ? 'Couldn’t load more' : 'Loading more…'}</Txt>{feed.isError && <Button label="Retry" variant="secondary" small forceDark onPress={() => feed.fetchNextPage()} />}</View>;
            return (
              <View style={{ height: pageH, alignItems: 'center', justifyContent: 'center', padding: space.xl, paddingTop: insets.top, gap: space.md }}>
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
          style={{ position: 'absolute', top: insets.top + 40, right: space.gutter, backgroundColor: c.surface2, borderRadius: radius.chip, paddingHorizontal: 12, minHeight: 32, justifyContent: 'center' }}>
          <Txt v="label" color={c.ink}>Back to top</Txt>
        </Pressable>
      )}
      <WhySheet item={why} onClose={() => setWhy(null)} />
      <ActionsSheet item={actions} onClose={() => setActions(null)} onWhy={setWhy} />
      <CommentsSheet item={comments} onClose={() => setComments(null)} />
    </View>
    </ForceDarkProvider>
  );
}
