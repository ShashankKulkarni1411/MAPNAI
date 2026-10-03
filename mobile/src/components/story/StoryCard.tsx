// Typographic story card (spec §8 card anatomy). Variants: hero (first must-know), standard, compact row.
import { Pressable, View } from 'react-native';
import { router } from 'expo-router';

import type { StoryItem } from '@/api/types';
import { impactBadge, sectionLabel, topicLabel } from '@/lib/labels';
import { ageLabel, hoursSince } from '@/lib/time';
import { EntryContext, useStoryCache } from '@/state/storyCache';
import { radius, space } from '@/theme/tokens';
import { useTheme } from '@/theme/useTheme';
import { Glyph, topicGlyph } from '../Glyph';
import { Txt } from '../Txt';
import { Chip, IconButton, Pill } from '../ui';
import { WhyLine } from './why';

export function openStory(item: StoryItem, context: EntryContext = 'slate', note?: string) {
  useStoryCache.getState().put({ item, context, note });
  router.push({ pathname: '/story/[id]', params: { id: item.article_id } });
}

export function summaryOf(item: StoryItem): { text: string | null; limited: boolean } {
  const s = item.summary_text ?? item.summary_short;
  if (s) return { text: s, limited: false };
  const snip = item.body_snippet ? item.body_snippet.slice(0, 300) : null;
  return { text: snip, limited: true };
}

export function Badges({ item, showSection = true, forceDark }: { item: StoryItem; showSection?: boolean; forceDark?: boolean }) {
  const impact = impactBadge(item.risk_level, item.unscored);
  const breaking = item.urgency_flag && hoursSince(item.published_at) < 6;
  const sec = item.section;
  const isMust = sec === 'must_know' || sec === 'just_in';
  if (!showSection && !impact && !breaking) return null;
  return (
    <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
      {showSection && sec && <Pill forceDark={forceDark} label={sectionLabel[sec]} kind={isMust ? 'must' : 'neutral'} />}
      {impact && <Pill forceDark={forceDark} label={impact} kind={impact === 'Major' ? 'impactFilled' : 'impactOutline'} />}
      {breaking && <Pill forceDark={forceDark} label="Breaking" kind="breaking" />}
    </View>
  );
}

export function MetaLine({ item, forceDark }: { item: StoryItem; forceDark?: boolean }) {
  const { c } = useTheme({ forceDark });
  const age = ageLabel(item.published_at);
  const source = item.source_name || (item.url ? item.url.replace(/^https?:\/\/(www\.)?/, '').split('/')[0] : '');
  const topic = topicLabel(item.topic);
  const n = item.cluster_size ?? 1;
  return (
    <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}
      accessible accessibilityLabel={`${topic}. ${source}${age ? `, ${age} ago` : ''}${n >= 2 ? `. ${n} sources` : ''}`}>
      <Glyph name={topicGlyph(item.topic)} size={14} color={item.topic === 'sports' ? c.sports : item.topic === 'entertainment_movies' ? c.film : c.general} />
      <Txt v="metaBold" numberOfLines={1} style={{ flexShrink: 1 }}>{source}</Txt>
      {age && <Txt v="meta" muted>{age}</Txt>}
      <View style={{ flex: 1 }} />
      {n >= 2 && (
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 4 }}>
          <Glyph name="stack" size={14} color={c.ink2} />
          <Txt v="meta" muted tabular>{n}</Txt>
        </View>
      )}
    </View>
  );
}

type Props = {
  item: StoryItem;
  variant?: 'hero' | 'standard' | 'compact';
  onWhy?: (item: StoryItem) => void;
  onActions?: (item: StoryItem) => void;
  context?: EntryContext;
};

export function StoryCard({ item, variant = 'standard', onWhy, onActions, context = 'slate' }: Props) {
  const { c } = useTheme();
  const read = useStoryCache((s) => !!s.opened[item.article_id]);
  const isMust = item.section === 'must_know' || item.section === 'just_in';
  const explore = item.section === 'explore';
  const { text, limited } = summaryOf(item);
  const headline = variant === 'hero' ? 'heroHeadline' : variant === 'compact' ? 'compactHeadline' : 'cardHeadline';
  const lines = variant === 'hero' ? 3 : 2;

  return (
    <Pressable
      onPress={() => openStory(item, context)}
      onLongPress={() => onActions?.(item)}
      accessibilityRole="button"
      accessibilityLabel={`${item.section ? sectionLabel[item.section] + '. ' : ''}${item.title}`}
      accessibilityActions={[{ name: 'activate' }, { name: 'longpress', label: 'Story actions' }, { name: 'why', label: 'Why this?' }]}
      onAccessibilityAction={(e) => {
        if (e.nativeEvent.actionName === 'longpress') onActions?.(item);
        if (e.nativeEvent.actionName === 'why') onWhy?.(item);
      }}
      style={({ pressed }) => ({
        backgroundColor: c.surface,
        borderRadius: radius.card,
        borderWidth: explore ? 1.5 : 1,
        borderStyle: explore ? 'dashed' : 'solid',
        borderColor: explore ? c.ink2 : c.hairline,
        padding: variant === 'compact' ? space.md : space.lg,
        paddingLeft: isMust && variant !== 'compact' ? space.lg + 4 : undefined,
        marginBottom: space.md,
        overflow: 'hidden',
        opacity: pressed ? 0.85 : 1,
        gap: variant === 'compact' ? 4 : 8,
      })}
    >
      {isMust && variant !== 'compact' && (
        <View style={{ position: 'absolute', left: 0, top: 0, bottom: 0, width: 4, backgroundColor: c.highlight }} />
      )}
      <View style={{ flexDirection: 'row', alignItems: 'flex-start' }}>
        <View style={{ flex: 1, gap: 8 }}>
          {variant !== 'compact' && <Badges item={item} />}
          <Txt v={headline} color={read ? c.ink2 : c.ink} numberOfLines={variant === 'compact' ? 2 : undefined}>{item.title}</Txt>
        </View>
        {onActions && <IconButton icon="dots" label="Story actions" onPress={() => onActions(item)} color={c.ink2} size={18} />}
      </View>
      {variant !== 'compact' && text && (
        <Txt v="body" muted numberOfLines={lines}>{limited ? `${text}…` : text}</Txt>
      )}
      {variant !== 'compact' && limited && <Txt v="label" muted>{item.topic === 'other' ? 'Limited analysis' : 'Summary not ready yet'}</Txt>}
      <WhyLine item={item} onPress={onWhy ? () => onWhy(item) : undefined} />
      {variant !== 'compact' && <MetaLine item={item} />}
      {variant !== 'compact' && !!item.entities?.length && (
        <View style={{ flexDirection: 'row', gap: 6, flexWrap: 'wrap' }}>
          {item.entities.slice(0, 3).map((e) => (
            <Chip key={e.key} label={e.name} onPress={() => router.push({ pathname: '/entity/[key]', params: { key: e.key } })} />
          ))}
        </View>
      )}
    </Pressable>
  );
}
