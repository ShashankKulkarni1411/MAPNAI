// R0 Recap card on Home: yesterday (or the week) in N stories, the overview's opening, the topic mix. Opens R1.
import { router } from 'expo-router';
import { Pressable, View } from 'react-native';

import type { Recap } from '@/api/types';
import { topicLabel } from '@/lib/labels';
import { localDate } from '@/lib/time';
import { radius, space } from '@/theme/tokens';
import { useTheme } from '@/theme/useTheme';
import { Glyph } from '../Glyph';
import { Txt } from '../Txt';

// "Yesterday in 10 stories", "Tuesday in 8 stories" (before 07:00 the newest is the day before), "The week in 15 stories"
export function recapHeadline(r: Recap): string {
  const n = r.items.length;
  const stories = `${n} ${n === 1 ? 'story' : 'stories'}`;
  if (r.kind === 'weekly') return `The week in ${stories}`;
  if (r.period === localDate(-1)) return `Yesterday in ${stories}`;
  return `${r.title.split(',')[0]} in ${stories}`;
}

// "6 Sports · 4 Film"
export function recapMix(r: Recap): string {
  const counts: Record<string, number> = {};
  r.items.forEach((i) => { counts[topicLabel(i.topic)] = (counts[topicLabel(i.topic)] ?? 0) + 1; });
  return Object.entries(counts).sort((a, b) => b[1] - a[1]).map(([t, n]) => `${n} ${t}`).join(' · ');
}

export function RecapCard({ recap, compact }: { recap: Recap; compact?: boolean }) {
  const { c } = useTheme();
  const open = () => router.push({ pathname: '/recap/[kind]', params: { kind: recap.kind } });
  const seen = recap.items.filter((i) => i.marks?.seen).length;

  if (compact)
    return (
      <Pressable onPress={open} accessibilityRole="button" accessibilityLabel={`${recapHeadline(recap)}, ${recap.title}`}
        style={{ flexDirection: 'row', alignItems: 'center', gap: 8, minHeight: 44, paddingHorizontal: space.md, borderRadius: radius.card, borderWidth: 1, borderColor: c.hairline }}>
        <Glyph name="stack" size={16} color={c.ink2} />
        <Txt v="metaBold" style={{ flex: 1 }} numberOfLines={1}>{recapHeadline(recap)}</Txt>
        <Txt v="meta" muted numberOfLines={1}>{recap.title}</Txt>
        <Glyph name="chevron" size={16} color={c.ink2} />
      </Pressable>
    );

  return (
    <Pressable onPress={open} accessibilityRole="button" accessibilityLabel={`${recapHeadline(recap)}. ${recap.overview?.text ?? ''}`}
      accessibilityHint="Opens the recap"
      style={({ pressed }) => ({ marginTop: space.md, padding: space.lg, borderRadius: radius.card, backgroundColor: c.ink, gap: space.sm, opacity: pressed ? 0.9 : 1 })}>
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
        <Glyph name="spotlight" size={16} color={c.highlight} />
        <Txt v="label" color={c.highlight}>{recap.kind === 'daily' ? 'DAILY RECAP' : 'WEEKLY RECAP'} · {recap.title.toUpperCase()}</Txt>
      </View>
      <Txt v="cardHeadline" color={c.bg}>{recapHeadline(recap)}</Txt>
      {!!recap.overview?.text && <Txt v="body" color={c.bg} numberOfLines={3}>{recap.overview.text}</Txt>}
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
        <Txt v="meta" color={c.bg} style={{ flex: 1, opacity: 0.8 }}>
          {recapMix(recap)}{seen ? ` · ${seen} read` : ''}
        </Txt>
        <Txt v="metaBold" color={c.highlight}>Start</Txt>
        <Glyph name="chevron" size={16} color={c.highlight} />
      </View>
      {recap.coverage.limited && (
        <Txt v="meta" color={c.bg} style={{ opacity: 0.8 }}>Limited coverage: fewer stories than usual were collected.</Txt>
      )}
    </Pressable>
  );
}
