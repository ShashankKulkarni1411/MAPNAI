// P2 What MAPNAI knows: declared inputs (editable) and learned ones (shown with strength, correctable).
import { router } from 'expo-router';
import { useState } from 'react';
import { ScrollView, Switch, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { api } from '@/api/endpoints';
import { invalidatePersona, useFollow, useProfile, useUserId } from '@/api/hooks';
import { Button } from '@/components/Button';
import { Connection, ConnectionSheet } from '@/components/follow/ConnectionSheet';
import { SignalBars } from '@/components/Glyph';
import { Txt } from '@/components/Txt';
import { CardSkeleton, InlineError, Row, SectionTitle, TopBar } from '@/components/ui';
import { importance, roleVerb, thetaLevel, titleCaseKey, topicLevelFor } from '@/lib/labels';
import { uiSentence } from '@/lib/profileWords';
import { useFeedback } from '@/state/feedback';
import { useSession } from '@/state/session';
import { radius, space } from '@/theme/tokens';
import { useTheme } from '@/theme/useTheme';

const theta = (b: [number, number]) => b[0] / (b[0] + b[1]);

export default function Knows() {
  const { c } = useTheme();
  const insets = useSafeAreaInsets();
  const uid = useUserId();
  const profile = useProfile();
  const follow = useFollow();
  const s = useSession();
  const [editing, setEditing] = useState<Connection | null>(null);
  const p = profile.data;
  const toast = useFeedback.getState().showToast;

  const learnedTopics = Object.entries(p?.beta ?? {})
    .filter(([k]) => k.startsWith('topic:') && ['topic:sports', 'topic:entertainment_movies'].includes(k))
    .map(([k, b]) => ({ topic: k === 'topic:sports' ? 'Sports' : 'Film', key: k.slice(6), th: theta(b), n: Math.round(b[0] + b[1] - 2) }));
  const learnedEntities = Object.entries(p?.beta ?? {})
    .filter(([k, b]) => k.startsWith('entity:') && !p?.exposures.some((e) => `entity:${e.key}` === k) && b[0] + b[1] - 2 >= 3)
    .map(([k, b]) => ({ key: k.slice(7), th: theta(b), n: Math.round(b[0] + b[1] - 2) }))
    .sort((a, b) => b.th - a.th)
    .slice(0, 8);

  const save = (conn: Connection) =>
    follow.mutate({ upsert: [{ key: conn.key, role: conn.role, weight: conn.weight }] }, {
      onSuccess: () => { setEditing(null); toast('Updated. Your brief reflects this on refresh'); },
    });
  const remove = (conn: Connection) =>
    follow.mutate({ remove: [conn.key] }, {
      onSuccess: () => { setEditing(null); toast(`Unfollowed ${conn.name}`, () => save(conn)); },
    });

  return (
    <View style={{ flex: 1, backgroundColor: c.bg, paddingTop: insets.top }}>
      <TopBar title="What MAPNAI knows" />
      <ScrollView contentContainerStyle={{ padding: space.gutter, paddingBottom: insets.bottom + space.xxl, maxWidth: 720, width: '100%', alignSelf: 'center' }}>
        {profile.isLoading && (<><CardSkeleton /><CardSkeleton /></>)}
        {profile.isError && <InlineError text="Couldn't load your profile." onRetry={() => profile.refetch()} />}
        {p && (
          <>
            {/* 1 In a sentence */}
            <View style={{ gap: 6 }}>
              {p.sentences.map((t, i) => <Txt key={i} v="body">{uiSentence(t)}</Txt>)}
            </View>

            {/* 2 Connections (declared) */}
            <SectionTitle title="Your connections" right={<Button label="Add" variant="text" small onPress={() => router.push('/profile/add-follows')} />} />
            {p.exposures.length === 0 && <Txt v="body" muted>You’re not following anything yet.</Txt>}
            {p.exposures.map((e) => (
              <Row key={e.key} title={e.name}
                sub={`You ${roleVerb[e.role]} · ${importance[e.weight].label}${e.provenance === 'confirmed' ? ' · Accepted suggestion' : ' · Added by you'}`}
                right={<SignalBars level={e.weight} color={c.ink} dim={c.hairline} />}
                onPress={() => setEditing({ key: e.key, name: e.name, role: e.role, weight: e.weight })} />
            ))}

            {/* 3 Topics (declared) */}
            <SectionTitle title="Topics" />
            <Row title="Sports" sub={topicLevelFor(p.topics.sports)} onPress={() => router.push('/profile/topics')} />
            <Row title="Film" sub={topicLevelFor(p.topics.entertainment_movies)} onPress={() => router.push('/profile/topics')} />
            <Txt v="meta" muted style={{ marginTop: 6 }}>Must-know stories about what you follow appear whatever you choose here.</Txt>

            {/* 4 Learned */}
            <SectionTitle title="What MAPNAI has learned" sub="From what you read. It never changes your follows on its own." />
            {learnedTopics.map((t) => {
              const lv = thetaLevel(t.th);
              const declared = topicLevelFor(p.topics[t.key]);
              const readsLike = lv.level >= 5 ? 'A lot' : lv.level <= 1 ? 'Not for me' : null;
              return (
                <View key={t.key} style={{ paddingVertical: 10, borderBottomWidth: 1, borderBottomColor: c.hairline, gap: 6 }}>
                  <View style={{ flexDirection: 'row', alignItems: 'center' }}>
                    <Txt v="body" style={{ flex: 1 }}>{t.topic}</Txt>
                    <Txt v="meta" muted>{lv.label}{t.n > 0 ? ` · based on ${t.n} signals` : ''}</Txt>
                  </View>
                  <LevelBar level={lv.level} />
                  {readsLike && readsLike !== declared && t.n >= 5 && (
                    <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
                      <Txt v="meta" style={{ flex: 1 }}>You said {declared}, but you read like {readsLike}. Update?</Txt>
                      <Button label="Update" small variant="secondary" onPress={async () => {
                        await api.patchTopics(uid, { [t.key]: readsLike === 'A lot' ? 1 : 0 }).catch(() => {});
                        invalidatePersona();
                      }} />
                    </View>
                  )}
                </View>
              );
            })}
            {learnedEntities.length > 0 && <Txt v="metaBold" style={{ marginTop: space.md }}>People and teams you read about</Txt>}
            {learnedEntities.map((e) => (
              <Row key={e.key} title={titleCaseKey(e.key)} sub={`${thetaLevel(e.th).label} · ${e.n} signals`}
                right={<Button label="Follow" small variant="secondary" onPress={() => setEditing({ key: e.key, name: titleCaseKey(e.key), role: 'follows', weight: 1 })} />} />
            ))}

            {/* 5 About you */}
            <SectionTitle title="About you" />
            <Row title="Age group" sub={s.birthYear ? ageBand(s.birthYear) : 'Not set'} />
            <Row title="Gender" sub={s.gender ?? 'Not set'} />
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: 12, paddingVertical: 10 }}>
              <View style={{ flex: 1 }}>
                <Txt v="body">Use my age group and gender for suggestions</Txt>
                <Txt v="meta" muted>Only shapes starting suggestions for things you haven't picked. A few of your own signals outweigh it. Never affects must-know stories or alerts.</Txt>
              </View>
              <Switch value={!!s.useDemographics} onValueChange={(v) => s.set({ useDemographics: v })} accessibilityLabel="Use my age group and gender for suggestions" />
            </View>

            {/* 6 Reading style */}
            <SectionTitle title="Reading style" />
            <Row title={`${cap(p.style.tone)} · ${cap(p.style.length)} · ${p.style.jargon === 'high' ? 'More jargon' : 'Less jargon'}`} onPress={() => router.push('/profile/style')} />
          </>
        )}
      </ScrollView>
      <ConnectionSheet value={editing} onClose={() => setEditing(null)} onSave={save} saving={follow.isPending}
        onRemove={editing && p?.exposures.some((e) => e.key === editing.key) ? remove : undefined} />
    </View>
  );
}

const cap = (x: string) => x[0].toUpperCase() + x.slice(1);

function ageBand(y: number) {
  const a = new Date().getFullYear() - y;
  return a < 25 ? '18–24' : a < 35 ? '25–34' : a < 45 ? '35–44' : '45+';
}

function LevelBar({ level }: { level: number }) {
  const { c } = useTheme();
  return (
    <View style={{ flexDirection: 'row', gap: 3 }} accessibilityElementsHidden>
      {[1, 2, 3, 4, 5].map((i) => (
        <View key={i} style={{ flex: 1, height: 6, borderRadius: radius.badge, backgroundColor: i <= level ? c.ink : c.surface2 }} />
      ))}
    </View>
  );
}
