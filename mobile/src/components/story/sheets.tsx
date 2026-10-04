// W1 Why sheet, W2 Story actions sheet, and the Flash comments sheet.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Share, TextInput, View } from 'react-native';
import { router } from 'expo-router';

import { errorCopy } from '@/api/client';
import { api } from '@/api/endpoints';
import { useUserId } from '@/api/hooks';
import type { Comment, StoryItem } from '@/api/types';
import { importance, sectionMeaning } from '@/lib/labels';
import { ageLabel } from '@/lib/time';
import { hideToday, react, toggleSave, useFeedback } from '@/state/feedback';
import { fonts, radius, space } from '@/theme/tokens';
import { useTheme } from '@/theme/useTheme';
import { Button } from '../Button';
import { Sheet } from '../Sheet';
import { Txt } from '../Txt';
import { Chip, InlineError, Row, Skeleton } from '../ui';

export function WhySheet({ item, onClose }: { item: StoryItem | null; onClose: () => void }) {
  const { c } = useTheme();
  const p = item?.explanation_parts;
  const close = (fn: () => void) => () => { onClose(); fn(); };
  return (
    <Sheet visible={!!item} onClose={onClose} title="Why you're seeing this">
      {item && (
        <>
          {item.section && <Txt v="metaBold">{sectionMeaning[item.section]}</Txt>}
          {item.explanation && <Txt v="body">{item.explanation}</Txt>}
          {p && (p.kind === 'direct' || p.kind === 'connected') && (
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6, flexWrap: 'wrap' }} accessibilityLabel="Connection path">
              <Chip label="You" />
              <Txt v="meta" muted>→ {p.role === 'covers' ? 'cover' : 'follow'} →</Txt>
              <Chip label={p.seed_name ?? ''} />
              {p.kind === 'connected' && (<><Txt v="meta" muted>→ often mentioned with →</Txt><Chip label={p.via_name ?? ''} /></>)}
            </View>
          )}
          {p?.kind === 'connected' && <Txt v="meta" muted>Often mentioned together, not necessarily related.</Txt>}
          {p?.seed_weight && <Txt v="meta" muted>{importance[p.seed_weight].label}: {importance[p.seed_weight].outcome}</Txt>}
          {!!p?.also?.length && <Txt v="meta" muted>Also linked: {p.also.join(', ')}</Txt>}
          <View style={{ borderTopWidth: 1, borderTopColor: c.hairline }}>
            <Row title="More like this" onPress={close(() => react(item.article_id, 'more'))} />
            <Row title="Less like this" onPress={close(() => react(item.article_id, 'less'))} />
            {p?.seed_name && (p.kind === 'direct' || p.kind === 'alert') && (
              <Row title={`Change importance of ${p.seed_name}`} onPress={close(() => router.push('/profile/knows'))} />
            )}
            {p?.kind === 'connected' && p.via_name && (
              <Row title={`Follow ${p.via_name}`} onPress={close(() => router.push({ pathname: '/entity/[key]', params: { key: p.via_name!.toLowerCase() } }))} />
            )}
            <Row title="Topic settings" onPress={close(() => router.push('/profile/topics'))} />
            <Row title="Show fewer like this today"
              onPress={close(() => hideToday(`${item.topic}|${item.entities?.[0]?.key ?? ''}`))} />
          </View>
          <Button label="How MAPNAI works" variant="text" onPress={close(() => router.push('/settings/how'))} style={{ alignSelf: 'flex-start' }} />
        </>
      )}
    </Sheet>
  );
}

export function ActionsSheet({ item, onClose, onWhy }: { item: StoryItem | null; onClose: () => void; onWhy: (i: StoryItem) => void }) {
  const saved = useFeedback((s) => (item ? !!s.saved[item.article_id] : false));
  const reaction = useFeedback((s) => (item ? s.reaction[item.article_id] : undefined));
  const close = (fn: () => void) => () => { onClose(); fn(); };
  return (
    <Sheet visible={!!item} onClose={onClose} title="Story actions">
      {item && (
        <View>
          <Row title={reaction === 'more' ? 'More like this ✓' : 'More like this'} onPress={close(() => react(item.article_id, 'more'))} />
          <Row title={reaction === 'less' ? 'Less like this ✓' : 'Less like this'} onPress={close(() => react(item.article_id, 'less'))} />
          <Row title={saved ? 'Remove from saved' : 'Save'} onPress={close(() => toggleSave(item.article_id))} />
          <Row title="Share" onPress={close(() => void Share.share({ message: `${item.title}\n${item.url}` }))} />
          <Row title="Why this?" onPress={close(() => onWhy(item))} />
          <Row title="Ask about this story" onPress={close(() => router.push({ pathname: '/ask', params: { article: item.article_id, title: item.title } }))} />
        </View>
      )}
    </Sheet>
  );
}

const MAX_COMMENT = 500;

export function CommentsSheet({ item, onClose }: { item: StoryItem | null; onClose: () => void }) {
  const { c } = useTheme();
  const uid = useUserId();
  const qc = useQueryClient();
  const [text, setText] = useState('');
  const id = item?.article_id ?? '';
  const list = useQuery({ queryKey: ['comments', id], queryFn: () => api.comments(id), enabled: !!item });
  const post = useMutation({
    mutationFn: (t: string) => api.addComment(uid, id, t),
    onSuccess: (cm) => {
      qc.setQueryData<Comment[]>(['comments', id], (old) => [cm, ...(old ?? [])]);
      setText('');
    },
  });
  const body = text.trim();
  return (
    <Sheet visible={!!item} onClose={onClose} title="Comments">
      {item && (
        <>
          <Txt v="meta" muted numberOfLines={2}>{item.title}</Txt>
          <View style={{ flexDirection: 'row', alignItems: 'flex-end', gap: space.sm }}>
            <TextInput
              value={text}
              onChangeText={setText}
              placeholder="Add a comment"
              placeholderTextColor={c.ink2}
              accessibilityLabel="Add a comment"
              multiline
              maxLength={MAX_COMMENT}
              style={{ flex: 1, minHeight: 44, maxHeight: 120, paddingHorizontal: 14, paddingVertical: 10, borderRadius: radius.button, borderWidth: 1.5, borderColor: c.hairline, backgroundColor: c.surface, color: c.ink, fontFamily: fonts.body400, fontSize: 16 }}
            />
            <Button label="Post" small disabled={!body || !uid} loading={post.isPending} onPress={() => post.mutate(body)} />
          </View>
          {post.isError && <Txt v="meta" color={c.impact} accessibilityLiveRegion="polite">{errorCopy(post.error, "Couldn't post. Try again.")}</Txt>}
          {list.isLoading && <View style={{ gap: 8 }}><Skeleton h={14} w="40%" /><Skeleton h={16} /><Skeleton h={14} w="30%" /></View>}
          {list.isError && <InlineError text="Couldn't load comments." onRetry={() => list.refetch()} />}
          {list.data && list.data.length === 0 && <Txt v="body" muted>No comments yet. Start the conversation.</Txt>}
          {list.data?.map((cm) => (
            <View key={cm.comment_id} style={{ gap: 2, paddingBottom: space.sm, borderBottomWidth: 1, borderBottomColor: c.hairline }}
              accessible accessibilityLabel={`${cm.author_name ?? 'Reader'}: ${cm.text}`}>
              <View style={{ flexDirection: 'row', gap: 6 }}>
                <Txt v="metaBold">{cm.user_id === uid ? 'You' : cm.author_name ?? 'Reader'}</Txt>
                {ageLabel(cm.created_at) && <Txt v="meta" muted>{ageLabel(cm.created_at)}</Txt>}
              </View>
              <Txt v="body">{cm.text}</Txt>
            </View>
          ))}
        </>
      )}
    </Sheet>
  );
}
