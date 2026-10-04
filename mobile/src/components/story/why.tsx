import { Pressable, View } from 'react-native';

import type { ExplanationParts, StoryItem } from '@/api/types';
import { roleVerb } from '@/lib/labels';
import { useTheme } from '@/theme/useTheme';
import { Glyph, GlyphName, SignalBars } from '../Glyph';
import { Txt } from '../Txt';

const KIND_GLYPH: Record<ExplanationParts['kind'], GlyphName> = {
  direct: 'person', connected: 'link', similar: 'echo', topic: 'echo', explore: 'compass', big_today: 'spotlight', alert: 'person',
};

// Short line for the card, built from structured parts. Falls back to the engine sentence, then a section default.
export function whyShort(item: StoryItem): { lead: string; name?: string; tail?: string; glyph: GlyphName } {
  const p = item.explanation_parts;
  if (p) {
    switch (p.kind) {
      case 'direct':
      case 'alert':
        return { lead: `You ${roleVerb[p.role ?? 'follows']}`, name: p.seed_name, glyph: 'person' };
      case 'connected':
        return { lead: 'Linked to', name: p.seed_name, glyph: 'link' };
      case 'similar':
        return { lead: `Similar to ‘${p.closest_title}’`, glyph: 'echo' };
      case 'topic':
        return { lead: `Because you read a lot of ${p.topic}`, glyph: 'echo' };
      case 'explore':
        return { lead: `Something new for you: ${p.topic}`, glyph: 'compass' };
      case 'big_today':
        return { lead: `Covered by ${item.cluster_size ?? 'many'} sources today`, glyph: 'spotlight' };
    }
  }
  if (item.explanation) return { lead: item.explanation, glyph: 'echo' };
  if (item.section === 'must_know' || item.section === 'more_you_need')
    return { lead: 'Big news about what you follow', glyph: 'person' };
  return { lead: 'Picked for you', glyph: 'echo' };
}

export function WhyLine({ item, onPress, forceDark, compact }: { item: StoryItem; onPress?: () => void; forceDark?: boolean; compact?: boolean }) {
  const { c } = useTheme({ forceDark });
  const w = whyShort(item);
  const highlight = item.section === 'must_know' || item.section === 'just_in';
  const level = item.explanation_parts?.seed_weight;
  const a11y = [w.lead, w.name].filter(Boolean).join(' ');
  const v = compact ? 'metaBold' : 'why';
  const leadV = compact ? 'meta' : 'why';
  return (
    <Pressable onPress={onPress} disabled={!onPress} hitSlop={6} accessibilityRole="button"
      accessibilityLabel={`Why this story: ${a11y}`} accessibilityHint="Opens why you're seeing this"
      style={{ flexDirection: 'row', alignItems: 'center', gap: compact ? 5 : 6, minHeight: compact ? 20 : 28, flexWrap: 'wrap' }}>
      <Glyph name={w.glyph} size={compact ? 13 : 15} color={c.ink2} />
      <Txt v={leadV} color={compact ? c.ink2 : undefined} numberOfLines={2} style={{ flexShrink: 1 }}>
        {w.lead}
        {w.name ? ' ' : ''}
      </Txt>
      {w.name && (
        <View style={{ backgroundColor: highlight ? c.highlight : 'transparent', paddingHorizontal: highlight ? 5 : 0, borderRadius: 3 }}>
          <Txt v={v} color={highlight ? c.onHighlight : c.ink}>{w.name}</Txt>
        </View>
      )}
      {level && <SignalBars level={level} color={c.ink} dim={c.hairline} />}
    </Pressable>
  );
}

export { KIND_GLYPH };
