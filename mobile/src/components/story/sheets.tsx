// W1 Why sheet and W2 Story actions sheet.
import { Share, View } from 'react-native';
import { router } from 'expo-router';

import type { StoryItem } from '@/api/types';
import { importance, sectionMeaning } from '@/lib/labels';
import { hideToday, react, toggleSave, useFeedback } from '@/state/feedback';
import { useTheme } from '@/theme/useTheme';
import { Button } from '../Button';
import { Sheet } from '../Sheet';
import { Txt } from '../Txt';
import { Chip, Row } from '../ui';

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
