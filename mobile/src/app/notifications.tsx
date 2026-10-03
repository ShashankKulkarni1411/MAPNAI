// N1 Notification center: alerts, suggested profile changes (and recap notices once recaps exist).
import AsyncStorage from '@react-native-async-storage/async-storage';
import { router } from 'expo-router';
import { useEffect, useState } from 'react';
import { Pressable, ScrollView, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { api } from '@/api/endpoints';
import { invalidatePersona, useAlerts, useProposals, useUserId } from '@/api/hooks';
import type { Alert } from '@/api/types';
import { Button } from '@/components/Button';
import { Txt } from '@/components/Txt';
import { CardSkeleton, EmptyState, IconButton, InlineError, Segmented, TopBar } from '@/components/ui';
import { ageLabel, hoursSince } from '@/lib/time';
import { radius, space } from '@/theme/tokens';
import { useTheme } from '@/theme/useTheme';

const READ_KEY = 'mapnai.alertsRead'; // MVP keeps read state on the device (read_at is Proposed)

export default function Notifications() {
  const { c } = useTheme();
  const insets = useSafeAreaInsets();
  const uid = useUserId();
  const alerts = useAlerts();
  const proposals = useProposals();
  const [seg, setSeg] = useState<'all' | 'alerts' | 'updates'>('all');
  const [read, setRead] = useState<string[]>([]);

  useEffect(() => {
    AsyncStorage.getItem(READ_KEY).then((r) => r && setRead(JSON.parse(r))).catch(() => {});
  }, []);
  const markRead = (ids: string[]) => {
    const next = [...new Set([...read, ...ids])];
    setRead(next);
    void AsyncStorage.setItem(READ_KEY, JSON.stringify(next)).catch(() => {});
  };

  const groups: [string, Alert[]][] = [
    ['Today', (alerts.data ?? []).filter((a) => hoursSince(a.created_at) < 24)],
    ['Yesterday', (alerts.data ?? []).filter((a) => hoursSince(a.created_at) >= 24 && hoursSince(a.created_at) < 48)],
    ['Earlier', (alerts.data ?? []).filter((a) => hoursSince(a.created_at) >= 48)],
  ];

  return (
    <View style={{ flex: 1, backgroundColor: c.bg, paddingTop: insets.top }}>
      <TopBar title="Notifications" right={<IconButton icon="gear" label="Notification settings" onPress={() => router.push('/settings/notifications')} />} />
      <ScrollView contentContainerStyle={{ padding: space.gutter, gap: space.md, paddingBottom: insets.bottom + space.xl }}>
        <Segmented label="Show" value={seg} onChange={setSeg}
          options={[{ label: 'All', value: 'all' }, { label: 'Alerts', value: 'alerts' }, { label: 'Updates', value: 'updates' }]} />
        {!!alerts.data?.length && <Button label="Mark all read" variant="text" small style={{ alignSelf: 'flex-end' }} onPress={() => markRead(alerts.data!.map((a) => a.alert_id))} />}
        {alerts.isLoading && (<><CardSkeleton /><CardSkeleton /></>)}
        {alerts.isError && <InlineError text="Couldn't load alerts." onRetry={() => alerts.refetch()} />}

        {seg !== 'updates' && groups.map(([title, list]) => list.length > 0 && (
          <View key={title} style={{ gap: space.sm }}>
            <Txt v="metaBold" muted>{title}</Txt>
            {list.map((a) => {
              const unread = !read.includes(a.alert_id);
              return (
                <Pressable key={a.alert_id} accessibilityRole="button" accessibilityLabel={`${unread ? 'Unread. ' : ''}${a.entity_name}: ${a.title}`}
                  onPress={() => { markRead([a.alert_id]); router.push({ pathname: '/story/[id]', params: { id: a.article_id, ctx: 'alert', note: a.explanation } }); }}
                  style={{ padding: space.md, borderRadius: radius.card, backgroundColor: c.surface, borderLeftWidth: 4, borderLeftColor: a.tier === 'major' ? c.impact : c.highlight, gap: 4 }}>
                  <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
                    {unread && <View style={{ width: 8, height: 8, borderRadius: 4, backgroundColor: c.ink }} />}
                    <Txt v="label" color={a.tier === 'major' ? c.impact : c.ink2}>{a.tier === 'major' ? 'Major' : 'High impact'}</Txt>
                    <Txt v="meta" muted>{ageLabel(a.created_at)}</Txt>
                    {a.deliver_after && <Txt v="label" muted>Held overnight</Txt>}
                  </View>
                  <Txt v="compactHeadline">{a.entity_name}: {a.title}</Txt>
                  <Txt v="meta" muted>{a.explanation}</Txt>
                </Pressable>
              );
            })}
          </View>
        ))}
        {seg !== 'updates' && alerts.data?.length === 0 && (
          <EmptyState text="No alerts yet. Alerts are for big news about what's Essential to you." action="Review follows" onAction={() => router.push('/profile/knows')} />
        )}

        {seg !== 'alerts' && (proposals.data ?? []).map((p) => (
          <View key={p.proposal_id} style={{ padding: space.md, borderRadius: radius.card, backgroundColor: c.surface2, gap: 8 }}>
            <Txt v="compactHeadline">Follow {p.entity_name}?</Txt>
            <Txt v="meta" muted>{p.reason}</Txt>
            <View style={{ flexDirection: 'row', gap: 8 }}>
              <Button label="Follow" small onPress={async () => { await api.decideProposal(uid, p.proposal_id, true).catch(() => {}); invalidatePersona(); }} />
              <Button label="Not now" variant="secondary" small onPress={async () => { await api.decideProposal(uid, p.proposal_id, false).catch(() => {}); void proposals.refetch(); }} />
            </View>
          </View>
        ))}
        {seg === 'updates' && !proposals.data?.length && <EmptyState text="No updates right now." />}
      </ScrollView>
    </View>
  );
}
