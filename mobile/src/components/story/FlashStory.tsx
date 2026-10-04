// F1 Flash story page: the article's ingested image full-bleed behind the text (faded into the background so the
// text stays readable), a reels-style action rail on the right, and why this story was picked under the summary.
import { useQuery } from '@tanstack/react-query';
import { Image } from 'expo-image';
import { router } from 'expo-router';
import { useState } from 'react';
import { Pressable, Share, StyleSheet, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import Svg, { Defs, LinearGradient, Rect, Stop } from 'react-native-svg';

import { api } from '@/api/endpoints';
import { followOf, useFollow, useProfile } from '@/api/hooks';
import type { ArticleImage, StoryItem } from '@/api/types';
import { Connection, ConnectionSheet } from '@/components/follow/ConnectionSheet';
import { importance, sectionLabel } from '@/lib/labels';
import { ageLabel } from '@/lib/time';
import { implicit, react, toggleSave, useFeedback } from '@/state/feedback';
import { radius, space } from '@/theme/tokens';
import { useTheme } from '@/theme/useTheme';
import { Glyph, GlyphName, topicGlyph } from '../Glyph';
import { Txt } from '../Txt';
import { Chip } from '../ui';
import { Badges, openStory } from './StoryCard';
import { WhyLine } from './why';

const RAIL_W = 60;

export function heroImage(item: StoryItem): ArticleImage | null {
  return item.media?.primary_image ?? null;
}

// The 30-second read: Agent 3's long summary (5–8 sentences), else the short one, else the start of the body
function flashText(item: StoryItem): string | null {
  return item.summary_long || item.summary_short || item.body_snippet || null;
}

// 1800 → 1.8K, 12400 → 12.4K, 1250000 → 1.3M
export function compactCount(n: number): string {
  if (n < 1000) return String(n);
  if (n < 1_000_000) return `${(n / 1000).toFixed(n < 100_000 ? 1 : 0).replace(/\.0$/, '')}K`;
  return `${(n / 1_000_000).toFixed(1).replace(/\.0$/, '')}M`;
}

// Fades the picture into the page colour: a light scrim under the progress bar, clear through the middle,
// solid behind the text
function Fade({ color }: { color: string }) {
  return (
    <Svg style={StyleSheet.absoluteFill} width="100%" height="100%" preserveAspectRatio="none">
      <Defs>
        <LinearGradient id="flashFade" x1="0" y1="0" x2="0" y2="1">
          <Stop offset="0" stopColor={color} stopOpacity={0.55} />
          <Stop offset="0.18" stopColor={color} stopOpacity={0} />
          <Stop offset="0.45" stopColor={color} stopOpacity={0.08} />
          <Stop offset="0.78" stopColor={color} stopOpacity={0.88} />
          <Stop offset="1" stopColor={color} stopOpacity={1} />
        </LinearGradient>
      </Defs>
      <Rect x="0" y="0" width="100%" height="100%" fill="url(#flashFade)" />
    </Svg>
  );
}

// No image ingested (or it failed to load): a topic-tinted field with the topic mark, never a stock photo
function NoImage({ item }: { item: StoryItem }) {
  const { c } = useTheme();
  const tint = item.topic === 'sports' ? c.sports : item.topic === 'entertainment_movies' ? c.film : c.general;
  return (
    <View style={{ flex: 1, backgroundColor: c.surface, alignItems: 'center', justifyContent: 'center' }}>
      <Svg style={StyleSheet.absoluteFill} width="100%" height="100%" preserveAspectRatio="none">
        <Defs>
          <LinearGradient id="flashTint" x1="0" y1="0" x2="1" y2="1">
            <Stop offset="0" stopColor={tint} stopOpacity={0.45} />
            <Stop offset="1" stopColor={tint} stopOpacity={0} />
          </LinearGradient>
        </Defs>
        <Rect x="0" y="0" width="100%" height="100%" fill="url(#flashTint)" />
      </Svg>
      <View style={{ opacity: 0.22, marginBottom: '25%' }}>
        <Glyph name={topicGlyph(item.topic)} size={112} color={tint} />
      </View>
    </View>
  );
}

// Fixed-size box, so nothing moves when the picture arrives; portrait photos keep their top (faces), others centre
function Backdrop({ item, height }: { item: StoryItem; height: number }) {
  const { c } = useTheme();
  const img = heroImage(item);
  const [failed, setFailed] = useState(false);
  const portrait = !!(img?.width && img?.height && img.height > img.width);
  return (
    <View pointerEvents="none" style={{ position: 'absolute', top: 0, left: 0, right: 0, height, backgroundColor: c.surface }}>
      {img && !failed ? (
        <Image
          source={{ uri: img.url }}
          style={{ flex: 1 }}
          contentFit="cover"
          contentPosition={portrait ? 'top center' : 'center'}
          transition={180}
          cachePolicy="memory-disk"
          recyclingKey={item.article_id}
          onError={() => setFailed(true)}
          accessible={!!img.alt}
          accessibilityLabel={img.alt ?? undefined}
        />
      ) : (
        <NoImage item={item} />
      )}
      <Fade color={c.bg} />
    </View>
  );
}

function SourceMark({ name }: { name: string }) {
  const { c } = useTheme();
  const initials = name.split(/[\s.-]+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join('').toUpperCase();
  return (
    <View style={{ width: 34, height: 34, borderRadius: 17, backgroundColor: c.ink, alignItems: 'center', justifyContent: 'center' }}>
      <Txt v="label" color={c.bg}>{initials || '•'}</Txt>
    </View>
  );
}

// Follow the story's main person / company / topic: the first one you don't follow yet, else edit the first
function FollowButton({ item }: { item: StoryItem }) {
  const { c } = useTheme();
  const profile = useProfile();
  const follow = useFollow();
  const [editing, setEditing] = useState<Connection | null>(null);
  const ents = item.entities ?? [];
  const target = ents.find((e) => !followOf(profile.data, e.key)) ?? ents[0];
  if (!target || !profile.data) return null;
  const f = followOf(profile.data, target.key);

  const save = (conn: Connection) =>
    follow.mutate({ upsert: [{ key: conn.key, role: conn.role, weight: conn.weight }] }, {
      onSuccess: () => { setEditing(null); useFeedback.getState().showToast(`Following ${conn.name} · ${importance[conn.weight].label}`); },
    });
  const remove = (conn: Connection) =>
    follow.mutate({ remove: [conn.key] }, {
      onSuccess: () => { setEditing(null); useFeedback.getState().showToast(`Unfollowed ${conn.name}`, () => save(conn)); },
    });

  return (
    <>
      <Pressable
        onPress={() => setEditing(f ? { key: f.key, name: f.name, role: f.role, weight: f.weight } : { key: target.key, name: target.name, role: 'follows', weight: 2 })}
        accessibilityRole="button"
        accessibilityLabel={f ? `Following ${target.name}. Edit` : `Follow ${target.name}`}
        hitSlop={6}
        style={({ pressed }) => ({
          minHeight: 32, maxWidth: 150, flexShrink: 1, paddingHorizontal: 12, borderRadius: radius.chip, borderWidth: 1.5,
          borderColor: f ? c.hairline : c.ink, flexDirection: 'row', alignItems: 'center', gap: 4, opacity: pressed ? 0.7 : 1,
        })}
      >
        {!f && <Glyph name="plus" size={14} color={c.ink} />}
        <Txt v="metaBold" color={c.ink} numberOfLines={1} style={{ flexShrink: 1 }}>{f ? `Following ${target.name}` : target.name}</Txt>
      </Pressable>
      <ConnectionSheet value={editing} onClose={() => setEditing(null)} onSave={save} saving={follow.isPending}
        onRemove={f ? remove : undefined} />
    </>
  );
}

function RailButton({ icon, label, count, active, activeColor, onPress }: {
  icon: GlyphName; label: string; count: number; active?: boolean; activeColor?: string; onPress: () => void;
}) {
  const { c } = useTheme();
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      accessibilityLabel={count > 0 ? `${label}, ${count}` : label}
      accessibilityState={{ selected: !!active }}
      hitSlop={4}
      style={({ pressed }) => ({ alignItems: 'center', justifyContent: 'center', minWidth: 52, minHeight: 58, gap: 3, opacity: pressed ? 0.6 : 1 })}
    >
      <Glyph name={icon} size={30} color={active ? activeColor ?? c.ink : c.ink} filled={active} />
      <Txt v="label" color={c.ink} tabular>{count > 0 ? compactCount(count) : label}</Txt>
    </Pressable>
  );
}

// Counts from the server leave the viewer out, so the viewer's on-screen state is added here exactly once
function ActionRail({ item, onComments }: { item: StoryItem; onComments: () => void }) {
  const { c } = useTheme();
  const reaction = useFeedback((s) => s.reaction[item.article_id]);
  const saved = useFeedback((s) => !!s.saved[item.article_id]);
  const [shared, setShared] = useState(false);
  const posted = useQuery({ queryKey: ['comments', item.article_id], queryFn: () => api.comments(item.article_id), enabled: false });
  const e = item.engagement;

  const share = async () => {
    try {
      const r = await Share.share({ message: `${item.title}\n${item.url}` });
      if (r.action === Share.sharedAction) {
        setShared(true);
        implicit(item.article_id, 'share');
      }
    } catch {}
  };

  return (
    <View style={{ alignItems: 'center', gap: space.sm }}>
      <RailButton icon="thumbUp" label="Like" active={reaction === 'more'} activeColor={c.highlight}
        count={(e?.likes ?? 0) + (reaction === 'more' ? 1 : 0)} onPress={() => react(item.article_id, 'more')} />
      <RailButton icon="thumbDown" label="Dislike" active={reaction === 'less'}
        count={(e?.dislikes ?? 0) + (reaction === 'less' ? 1 : 0)} onPress={() => react(item.article_id, 'less')} />
      <RailButton icon="comment" label="Comment" count={Math.max(e?.comments ?? 0, posted.data?.length ?? 0)} onPress={onComments} />
      <RailButton icon="bookmark" label={saved ? 'Saved' : 'Save'} active={saved} activeColor={c.highlight}
        count={(e?.saves ?? 0) + (saved ? 1 : 0)} onPress={() => toggleSave(item.article_id)} />
      <RailButton icon="forward" label="Share" count={(e?.shares ?? 0) + (shared ? 1 : 0)} onPress={share} />
    </View>
  );
}

type Props = {
  item: StoryItem;
  index: number;
  total: number;
  inBrief: boolean;
  height: number;
  showHint: boolean;
  onWhy: () => void;
  onActions: () => void;
  onComments: () => void;
  onNext: () => void;
  onPrev: () => void;
};

export function FlashStory({ item, index, total, inBrief, height, showHint, onWhy, onActions, onComments, onNext, onPrev }: Props) {
  const { c } = useTheme();
  const insets = useSafeAreaInsets();
  const text = flashText(item);
  const age = ageLabel(item.published_at);
  const source = item.source_name || (item.url ? item.url.replace(/^https?:\/\/(www\.)?/, '').split('/')[0] : '');
  // the summary gets the room the image, header and the rest of the text leave (8 lines ≈ 30 s of reading)
  const lines = Math.max(3, Math.min(8, Math.floor((height - 430) / 24)));

  return (
    <View style={{ height, overflow: 'hidden', backgroundColor: c.bg }}>
      <Backdrop item={item} height={Math.round(height * 0.68)} />

      {/* Progress across the brief; after the divider it becomes a plain label */}
      <View style={{ paddingTop: insets.top + space.sm, paddingHorizontal: space.gutter, gap: 6 }}>
        {inBrief ? (
          <View style={{ gap: 6 }} accessibilityLabel={`${index + 1} of ${total}`}>
            <View style={{ flexDirection: 'row', gap: 3 }}>
              {Array.from({ length: total }).map((_, i) => (
                <View key={i} style={{ flex: 1, height: 3, borderRadius: 2, backgroundColor: i <= index ? c.ink : c.hairline }} />
              ))}
            </View>
            <Txt v="label" color={c.ink} style={{ alignSelf: 'flex-end' }} tabular>{index + 1} of {total}</Txt>
          </View>
        ) : (
          <Txt v="label" color={c.ink}>{item.section === 'big_today' ? 'Outside your usual: a big story today' : sectionLabel.feed}</Txt>
        )}
        {showHint && (
          <View style={{ alignSelf: 'center', backgroundColor: c.scrim, borderRadius: radius.chip, paddingHorizontal: 14, paddingVertical: 6 }}>
            <Txt v="meta" color={c.ink}>Swipe up for the next story · tap to read · hold for more</Txt>
          </View>
        )}
      </View>

      <Pressable
        style={{ flex: 1, justifyContent: 'flex-end', paddingLeft: space.gutter, paddingRight: RAIL_W + space.md, paddingBottom: space.lg }}
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
        <View style={{ gap: space.sm + 2, maxWidth: 600 }}>
          <Badges item={item} />
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: space.sm }}>
            <SourceMark name={source} />
            <Txt v="metaBold" color={c.ink} numberOfLines={1} style={{ flexShrink: 1, minWidth: 48 }}>{source}</Txt>
            {age && <Txt v="meta" color={c.ink2} numberOfLines={1} style={{ flexShrink: 0 }}>{age} ago</Txt>}
            <FollowButton item={item} />
          </View>
          <Txt v="flashHeadline" color={c.ink} numberOfLines={4}>{item.title}</Txt>
          {text && <Txt v="flashSummary" color={c.ink2} numberOfLines={lines}>{text}</Txt>}
          <WhyLine item={item} onPress={onWhy} />
          {!!item.entities?.length && (
            <View style={{ flexDirection: 'row', gap: 6, flexWrap: 'wrap' }}>
              {item.entities.slice(0, 3).map((e) => (
                <Chip key={e.key} label={e.name} onPress={() => router.push({ pathname: '/entity/[key]', params: { key: e.key } })} />
              ))}
            </View>
          )}
        </View>
      </Pressable>

      <View style={{ position: 'absolute', right: 4, bottom: space.lg, width: RAIL_W, alignItems: 'center' }}>
        <ActionRail item={item} onComments={onComments} />
      </View>
    </View>
  );
}
