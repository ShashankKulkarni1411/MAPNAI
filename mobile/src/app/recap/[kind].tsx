// R1 Recap: the day before (daily, ready 07:00) or the week to Sunday 22:00 (weekly), the same stories for every reader.
// A cover with the overview, one story per page in the Flash layout (numbered, with the week's sections), then an end
// page. Finite by design: it never continues into the feed. Stories hidden with "Hide like this" today stay hidden.
import { Image } from 'expo-image';
import { router, useLocalSearchParams } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { ReactNode, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { FlatList, LayoutChangeEvent, Pressable, View, ViewToken } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { useRecap } from '@/api/hooks';
import type { RecapItem, RecapKind, StoryItem } from '@/api/types';
import { Button } from '@/components/Button';
import { Glyph } from '@/components/Glyph';
import { FlashStory, heroImage } from '@/components/story/FlashStory';
import { recapHeadline, recapMix } from '@/components/story/RecapCard';
import { ActionsSheet, CommentsSheet, WhySheet } from '@/components/story/sheets';
import { Txt } from '@/components/Txt';
import { clockLabel, isoDate } from '@/lib/time';
import { hydrate, implicit, useFeedback } from '@/state/feedback';
import { usePrefs } from '@/state/prefs';
import { radius, space } from '@/theme/tokens';
import { ForceDarkProvider, useTheme } from '@/theme/useTheme';

type Row = { kind: 'cover' } | { kind: 'story'; item: RecapItem; n: number } | { kind: 'end' };

export default function RecapScreen() {
  const params = useLocalSearchParams<{ kind: string }>();
  const kind: RecapKind = params.kind === 'weekly' ? 'weekly' : 'daily';
  const otherKind: RecapKind = kind === 'daily' ? 'weekly' : 'daily';
  const flashDark = usePrefs((s) => s.flashAlwaysDark);
  const { c, isDark } = useTheme({ forceDark: flashDark });
  const insets = useSafeAreaInsets();
  const recap = useRecap(kind);
  const other = useRecap(otherKind);
  const hidden = useFeedback((s) => (s.hiddenToday.day === isoDate() ? s.hiddenToday.keys : []));
  const [h, setH] = useState(0);
  const [index, setIndex] = useState(0);
  const [why, setWhy] = useState<StoryItem | null>(null);
  const [actions, setActions] = useState<StoryItem | null>(null);
  const [comments, setComments] = useState<StoryItem | null>(null);
  const listRef = useRef<FlatList<Row>>(null);

  const r = recap.data;
  const items = useMemo(
    () => (r?.items ?? []).filter((i) => !hidden.includes(`${i.topic}|${i.entities?.[0]?.key ?? ''}`)),
    [r, hidden],
  );
  const sectionTitle = useMemo(() => Object.fromEntries((r?.sections ?? []).map((s) => [s.key, s.title])), [r]);
  const rows: Row[] = useMemo(
    () => (r ? [{ kind: 'cover' }, ...items.map((item, n) => ({ kind: 'story' as const, item, n })), { kind: 'end' }] : []),
    [r, items],
  );

  // Your own like / dislike / save from earlier sessions
  useEffect(() => { hydrate(items); }, [items]);

  // Dwell, as in Flash: active time on a story, capped at 120 s
  const shownAt = useRef<{ id: string; t: number } | null>(null);
  const onViewable = useRef(({ viewableItems }: { viewableItems: ViewToken<Row>[] }) => {
    const v = viewableItems[0];
    if (!v) return;
    const prev = shownAt.current;
    if (prev) implicit(prev.id, 'dwell', Math.min(120, (Date.now() - prev.t) / 1000));
    setIndex(v.index ?? 0);
    shownAt.current = v.item.kind === 'story' ? { id: v.item.item.article_id, t: Date.now() } : null;
  }).current;

  useEffect(() => {
    const urls = rows.slice(index, index + 3)
      .map((row) => (row.kind === 'story' ? heroImage(row.item)?.url : undefined))
      .filter((u): u is string => !!u);
    if (urls.length) void Image.prefetch(urls, 'memory-disk').catch(() => {});
  }, [index, rows]);

  const goTo = useCallback((i: number) => {
    if (i >= 0 && i < rows.length) listRef.current?.scrollToIndex({ index: i, animated: true });
  }, [rows.length]);

  const close = () => (router.canGoBack() ? router.back() : router.replace('/(tabs)'));
  const onLayout = (e: LayoutChangeEvent) => setH(e.nativeEvent.layout.height);

  // weekly: the section ("Stories of the week", "Monday 19 Oct"); both: "You read this"
  const kicker = (item: RecapItem) =>
    [kind === 'weekly' ? sectionTitle[item.group] : null, item.marks?.seen ? 'You read this' : null].filter(Boolean).join(' · ');

  const page = (children: ReactNode) => (
    <View style={{ height: h, justifyContent: 'center', padding: space.gutter, paddingTop: insets.top + space.xl, gap: space.md }}>
      {children}
    </View>
  );

  const renderRow = ({ item: row, index: i }: { item: Row; index: number }) => {
    if (row.kind === 'story')
      return (
        <FlashStory item={row.item} index={row.n} total={items.length} inBrief height={h} showHint={false}
          kicker={kicker(row.item)} entry="recap"
          onWhy={() => setWhy(row.item)} onActions={() => setActions(row.item)} onComments={() => setComments(row.item)}
          onNext={() => goTo(i + 1)} onPrev={() => goTo(i - 1)} />
      );
    if (row.kind === 'cover' && r)
      return page(
        <View style={{ gap: space.md, maxWidth: 600 }}>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
            <Glyph name="spotlight" size={16} color={c.highlight} />
            <Txt v="label" color={c.highlight}>{kind === 'daily' ? 'DAILY RECAP' : 'WEEKLY RECAP'}</Txt>
          </View>
          <Txt v="screenTitle" color={c.ink}>{r.title}</Txt>
          <Txt v="cardHeadline" color={c.ink}>{recapHeadline({ ...r, items })}</Txt>
          {!!r.overview?.text && <Txt v="summary" color={c.ink}>{r.overview.text}</Txt>}
          <Txt v="meta" color={c.ink2}>
            {recapMix({ ...r, items })} · the same for every reader, whatever you follow
          </Txt>
          {r.coverage.limited && (
            <View style={{ backgroundColor: c.surface, borderRadius: radius.card, padding: space.md }}>
              <Txt v="meta" color={c.ink}>Limited coverage: fewer stories than usual were collected for this {kind === 'daily' ? 'day' : 'week'}.</Txt>
            </View>
          )}
          {items.length > 0 ? (
            <Button label="Start" forceDark={flashDark} onPress={() => goTo(1)} />
          ) : (
            <Txt v="body" color={c.ink}>No big stories in Sports or Film for this {kind === 'daily' ? 'day' : 'week'}.</Txt>
          )}
          <Txt v="meta" color={c.ink2}>Built {clockLabel(r.generated_at)} · next one {kind === 'daily' ? 'tomorrow' : 'on Sunday'} at {clockLabel(r.next_at)}</Txt>
        </View>,
      );
    const next = other.data && other.data.items.length > 0 ? other.data : null;
    return page(
      <View style={{ gap: space.md, alignItems: 'stretch', maxWidth: 600 }}>
        <Txt v="heroHeadline" color={c.ink} style={{ textAlign: 'center' }}>
          You’re caught up on {kind === 'daily' ? r?.title.split(',')[0] : 'the week'}
        </Txt>
        {next && <Button label={recapHeadline(next)} forceDark={flashDark} onPress={() => router.replace({ pathname: '/recap/[kind]', params: { kind: otherKind } })} />}
        <Button label="Keep going in Flash" variant="secondary" forceDark={flashDark} onPress={() => router.navigate('/(tabs)/flash')} />
        <Button label="Back to top" variant="text" forceDark={flashDark} onPress={() => goTo(0)} />
      </View>,
    );
  };

  return (
    <ForceDarkProvider value={flashDark}>
      <StatusBar style={isDark ? 'light' : 'dark'} />
      <View style={{ flex: 1, backgroundColor: c.bg }} onLayout={onLayout}>
        {!r && h > 0 && page(
          <View style={{ alignItems: 'center', gap: space.md }}>
            <Txt v="sectionTitle" color={c.ink}>{recap.isError ? 'Couldn’t load the recap' : 'Loading the recap'}</Txt>
            {recap.isError && <Button label="Retry" variant="secondary" small forceDark={flashDark} onPress={() => recap.refetch()} />}
          </View>,
        )}
        {r && h > 0 && (
          <FlatList
            ref={listRef}
            data={rows}
            keyExtractor={(row, i) => (row.kind === 'story' ? row.item.article_id : `${row.kind}-${i}`)}
            pagingEnabled
            showsVerticalScrollIndicator={false}
            decelerationRate="fast"
            snapToInterval={h}
            getItemLayout={(_, i) => ({ length: h, offset: h * i, index: i })}
            onViewableItemsChanged={onViewable}
            viewabilityConfig={{ itemVisiblePercentThreshold: 90, minimumViewTime: 1000 }}
            windowSize={5}
            renderItem={renderRow}
          />
        )}
        <Pressable onPress={close} accessibilityRole="button" accessibilityLabel="Close recap" hitSlop={8}
          style={{ position: 'absolute', top: insets.top + 36, right: space.gutter, width: 36, height: 36, borderRadius: 18, backgroundColor: c.surface2, alignItems: 'center', justifyContent: 'center' }}>
          <Glyph name="close" size={18} color={c.ink} />
        </Pressable>
      </View>
      <WhySheet item={why} onClose={() => setWhy(null)} />
      <ActionsSheet item={actions} onClose={() => setActions(null)} onWhy={setWhy} />
      <CommentsSheet item={comments} onClose={() => setComments(null)} />
    </ForceDarkProvider>
  );
}
