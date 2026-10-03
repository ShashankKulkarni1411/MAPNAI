// Headline deck for O3 (and later X2 "Tune your brief"). Right = more like this, left = not for me, up or Skip = skip.
// Every gesture has a button and a screen-reader action (spec §31).
import { useMemo, useRef, useState } from 'react';
import { AccessibilityInfo, Animated, PanResponder, Pressable, View } from 'react-native';

import type { Headline } from '@/api/types';
import { topicLabel } from '@/lib/labels';
import { ageLabel } from '@/lib/time';
import { radius, space } from '@/theme/tokens';
import { useTheme } from '@/theme/useTheme';
import { Glyph, GlyphName, topicGlyph } from './Glyph';
import { Txt } from './Txt';

export type Judgement = 'like' | 'dislike' | 'skip';

type Props = { items: Headline[]; onJudge: (h: Headline, j: Judgement) => void; onUndo: (h: Headline) => void; onDone: () => void };

export function SwipeDeck({ items, onJudge, onUndo, onDone }: Props) {
  const { c } = useTheme();
  const [i, setI] = useState(0);
  const pos = useRef(new Animated.ValueXY()).current;
  const cur = items[i];

  const judge = (j: Judgement) => {
    if (!cur) return;
    const to = j === 'like' ? { x: 500, y: 0 } : j === 'dislike' ? { x: -500, y: 0 } : { x: 0, y: -700 };
    Animated.timing(pos, { toValue: to, duration: 180, useNativeDriver: true }).start(() => {
      pos.setValue({ x: 0, y: 0 });
      onJudge(cur, j);
      AccessibilityInfo.announceForAccessibility(j === 'like' ? 'More like this' : j === 'dislike' ? 'Not for me' : 'Skipped');
      if (i + 1 >= items.length) onDone();
      setI((n) => n + 1);
    });
  };

  const pan = useMemo(
    () =>
      PanResponder.create({
        onMoveShouldSetPanResponder: (_, g) => Math.abs(g.dx) > 8 || Math.abs(g.dy) > 8,
        onPanResponderMove: Animated.event([null, { dx: pos.x, dy: pos.y }], { useNativeDriver: false }),
        onPanResponderRelease: (_, g) => {
          if (g.dx > 110) judge('like');
          else if (g.dx < -110) judge('dislike');
          else if (g.dy < -110) judge('skip');
          else Animated.spring(pos, { toValue: { x: 0, y: 0 }, useNativeDriver: true }).start();
        },
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [i, items],
  );

  const rotate = pos.x.interpolate({ inputRange: [-300, 0, 300], outputRange: ['-10deg', '0deg', '10deg'] });

  const btn = (icon: GlyphName, label: string, j: Judgement) => (
    <Pressable onPress={() => judge(j)} accessibilityRole="button" accessibilityLabel={label} disabled={!cur}
      style={{ width: 64, height: 64, borderRadius: 32, borderWidth: 1.5, borderColor: c.hairline, backgroundColor: c.surface, alignItems: 'center', justifyContent: 'center' }}>
      <Glyph name={icon} size={26} color={c.ink} />
    </Pressable>
  );

  return (
    <View style={{ gap: space.lg }}>
      <View style={{ flexDirection: 'row', alignItems: 'center' }}>
        <Txt v="meta" muted tabular style={{ flex: 1 }}>{cur ? `${i + 1} of ${items.length}` : `${items.length} of ${items.length}`}</Txt>
        <Pressable disabled={i === 0} onPress={() => { const prev = items[i - 1]; if (prev) { onUndo(prev); setI(i - 1); } }}
          accessibilityRole="button" accessibilityLabel="Undo last card" hitSlop={8}
          style={{ minHeight: 44, flexDirection: 'row', alignItems: 'center', gap: 6, opacity: i === 0 ? 0.35 : 1 }}>
          <Glyph name="undo" color={c.ink} />
          <Txt v="metaBold">Undo</Txt>
        </Pressable>
      </View>
      <View style={{ height: 260 }}>
        {cur ? (
          <Animated.View {...pan.panHandlers}
            accessible accessibilityLabel={`${topicLabel(cur.topic)}. ${cur.title}. ${cur.source}`}
            accessibilityActions={[{ name: 'like', label: 'More like this' }, { name: 'dislike', label: 'Not for me' }, { name: 'skip', label: 'Skip' }]}
            onAccessibilityAction={(e) => judge(e.nativeEvent.actionName as Judgement)}
            style={{ flex: 1, backgroundColor: c.surface, borderRadius: radius.card, borderWidth: 1, borderColor: c.hairline, padding: space.xl, gap: space.md, justifyContent: 'center', transform: [{ translateX: pos.x }, { translateY: pos.y }, { rotate }] }}>
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
              <Glyph name={topicGlyph(cur.topic)} size={15} color={cur.topic === 'sports' ? c.sports : c.film} />
              <Txt v="label" muted>{topicLabel(cur.topic)}</Txt>
            </View>
            <Txt v="heroHeadline">{cur.title}</Txt>
            <View style={{ flexDirection: 'row', gap: 6 }}>
              <Txt v="metaBold">{cur.source}</Txt>
              {ageLabel(cur.published_at) && <Txt v="meta" muted>{ageLabel(cur.published_at)}</Txt>}
            </View>
          </Animated.View>
        ) : (
          <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center' }}><Txt v="body" muted>That’s all ten.</Txt></View>
        )}
      </View>
      <View style={{ flexDirection: 'row', justifyContent: 'center', gap: space.xl }}>
        {btn('close', 'Not for me', 'dislike')}
        {btn('skip', 'Skip', 'skip')}
        {btn('heart', 'More like this', 'like')}
      </View>
    </View>
  );
}
