// P8 Suggestions: learned changes arrive as suggestions the user accepts or rejects; nothing changes silently.
import { useState } from 'react';
import { Pressable, View } from 'react-native';

import { api } from '@/api/endpoints';
import { invalidatePersona, useProposals, useUserId } from '@/api/hooks';
import type { Proposal } from '@/api/types';
import { Button } from '@/components/Button';
import { Connection, ConnectionSheet } from '@/components/follow/ConnectionSheet';
import { FormScreen } from '@/components/Screen';
import { openStory } from '@/components/story/StoryCard';
import { Txt } from '@/components/Txt';
import { CardSkeleton, EmptyState, TopBar } from '@/components/ui';
import { importance, roleVerb } from '@/lib/labels';
import { useFeedback } from '@/state/feedback';
import { radius, space } from '@/theme/tokens';
import { useTheme } from '@/theme/useTheme';

export default function Suggestions() {
  const { c } = useTheme();
  const uid = useUserId();
  const q = useProposals();
  const [editing, setEditing] = useState<{ p: Proposal; conn: Connection } | null>(null);
  const [overrides, setOverrides] = useState<Record<string, Connection>>({});

  async function accept(p: Proposal) {
    await api.decideProposal(uid, p.proposal_id, true).catch(() => {});
    const o = overrides[p.proposal_id];
    if (o && (o.role !== p.role || o.weight !== p.weight)) {
      await api.patchExposures(uid, [{ key: p.entity_key, role: o.role, weight: o.weight }]).catch(() => {});
    }
    invalidatePersona();
    useFeedback.getState().showToast(`Following ${p.entity_name} · ${importance[(o ?? p).weight].label}`);
  }

  return (
    <FormScreen top={<TopBar title="Suggestions" />}>
      {q.isLoading && <CardSkeleton />}
      {q.data?.length === 0 && <EmptyState text="No suggestions right now. MAPNAI suggests a follow when you keep reading about someone." />}
      {q.data?.map((p) => {
        const conn = overrides[p.proposal_id] ?? { key: p.entity_key, name: p.entity_name, role: p.role, weight: p.weight };
        return (
          <View key={p.proposal_id} style={{ backgroundColor: c.surface, borderRadius: radius.card, borderWidth: 1, borderColor: c.hairline, padding: space.lg, gap: space.sm }}>
            <Txt v="cardHeadline">Follow {p.entity_name}?</Txt>
            <Txt v="body" muted>{p.reason}</Txt>
            {p.evidence.map((e) => (
              <Pressable key={e.article_id} accessibilityRole="link"
                onPress={() => openStory({ article_id: e.article_id, title: e.title, url: '', topic: 'other' }, 'deeplink')}>
                <Txt v="meta" style={{ textDecorationLine: 'underline' }}>{e.title}</Txt>
              </Pressable>
            ))}
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
              <Txt v="meta" style={{ flex: 1 }}>You {roleVerb[conn.role]} · {importance[conn.weight].label}</Txt>
              <Button label="Change" variant="text" small onPress={() => setEditing({ p, conn })} />
            </View>
            <View style={{ flexDirection: 'row', gap: 8 }}>
              <Button label="Accept" small onPress={() => accept(p)} />
              <Button label="Not now" variant="secondary" small onPress={async () => { await api.decideProposal(uid, p.proposal_id, false).catch(() => {}); void q.refetch(); }} />
            </View>
          </View>
        );
      })}
      <ConnectionSheet value={editing?.conn ?? null} onClose={() => setEditing(null)}
        onSave={(conn) => { if (editing) setOverrides((o) => ({ ...o, [editing.p.proposal_id]: conn })); setEditing(null); }} />
    </FormScreen>
  );
}
