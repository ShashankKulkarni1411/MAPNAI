// S1 Story page: why it matters to you before what happened. Headline and context come from the card that
// opened it (instant); summary, impact and related load after. MAPNAI never reproduces the full article.
import { useQuery } from '@tanstack/react-query';
import { router, useLocalSearchParams } from 'expo-router';
import * as WebBrowser from 'expo-web-browser';
import { useEffect, useRef, useState } from 'react';
import { Pressable, ScrollView, Share, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { api } from '@/api/endpoints';
import { followOf, useFollow, useProfile, useUserId } from '@/api/hooks';
import type { StoryItem } from '@/api/types';
import { Button } from '@/components/Button';
import { Connection, ConnectionSheet } from '@/components/follow/ConnectionSheet';
import { SignalBars } from '@/components/Glyph';
import { Sheet } from '@/components/Sheet';
import { Badges, openStory, summaryOf } from '@/components/story/StoryCard';
import { WhySheet } from '@/components/story/sheets';
import { Txt } from '@/components/Txt';
import { Chip, IconButton, InlineError, Segmented, SectionTitle, Skeleton, TopBar } from '@/components/ui';
import { importance, sectionLabel, topicLabel } from '@/lib/labels';
import { ageLabel } from '@/lib/time';
import { calibrate, implicit, react, toggleSave, useFeedback } from '@/state/feedback';
import { useSession } from '@/state/session';
import { EntryContext, useStoryCache } from '@/state/storyCache';
import { radius, space } from '@/theme/tokens';
import { useTheme } from '@/theme/useTheme';

const CTX_LABEL: Partial<Record<EntryContext, string>> = { alert: 'Alert', developing: 'Developing', cited: 'Cited', recap: 'Recap' };

export default function Story() {
  const { c } = useTheme();
  const insets = useSafeAreaInsets();
  const { id, ctx, note } = useLocalSearchParams<{ id: string; ctx?: EntryContext; note?: string }>();
  const uid = useUserId();
  const entry = useStoryCache((s) => s.entries[id]);
  const markOpened = useStoryCache((s) => s.markOpened);
  const context: EntryContext = (ctx as EntryContext) ?? entry?.context ?? 'deeplink';
  const detail = useQuery({ queryKey: ['story', id, uid], queryFn: () => api.story(id, uid) });
  const item: StoryItem | undefined = detail.data ?? entry?.item;
  const fromSlate = context === 'slate' ? entry?.item : undefined;
  const profile = useProfile();
  const follow = useFollow();
  const saved = useFeedback((s) => !!s.saved[id]);
  const reaction = useFeedback((s) => s.reaction[id]);
  const cal = useFeedback((s) => s.calibration[id]);
  const [impactOpen, setImpactOpen] = useState(false);
  const [why, setWhy] = useState<StoryItem | null>(null);
  const [menu, setMenu] = useState(false);
  const [editing, setEditing] = useState<Connection | null>(null);
  const [showOriginal, setShowOriginal] = useState(false);
  const [stylePrompt, setStylePrompt] = useState(false);
  const session = useSession();

  // open after 3 s on screen; dwell (active seconds) on exit, above 15 s, once per story per day
  const start = useRef(Date.now());
  useEffect(() => {
    const t = setTimeout(() => {
      implicit(id, 'open');
      markOpened(id);
      const n = session.storiesOpened + 1;
      session.set({ storiesOpened: n });
      if (n === 3) setStylePrompt(true); // X3: ask reading style just in time
    }, 3000);
    return () => {
      clearTimeout(t);
      implicit(id, 'dwell', Math.min(600, (Date.now() - start.current) / 1000));
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  async function openOriginal(url: string) {
    implicit(id, 'open');
    await WebBrowser.openBrowserAsync(url).catch(() => {});
  }

  if (!item) {
    return (
      <View style={{ flex: 1, backgroundColor: c.bg, paddingTop: insets.top }}>
        <TopBar />
        <View style={{ padding: space.gutter, gap: space.md }}>
          {detail.isError ? <InlineError text="This story is no longer available." /> : (<><Skeleton h={28} /><Skeleton h={28} w="70%" /><Skeleton h={120} /></>)}
        </View>
      </View>
    );
  }

  const parts = fromSlate?.explanation_parts ?? detail.data?.personal?.parts;
  const explanation = fromSlate?.explanation ?? detail.data?.personal?.explanation;
  const isMust = fromSlate?.section === 'must_know';
  const { text, limited } = summaryOf(item);
  const long = detail.data?.summary_long;
  const risk = detail.data?.risk;
  const rendered = !!item.summary_text && !showOriginal;
  const sectionTag = context === 'slate' && fromSlate?.section ? sectionLabel[fromSlate.section] : CTX_LABEL[context];
  const style = profile.data?.style;

  return (
    <View style={{ flex: 1, backgroundColor: c.bg, paddingTop: insets.top }}>
      <TopBar
        title={item.source_name ?? undefined}
        right={
          <>
            <IconButton icon="bookmark" filled={saved} label={saved ? 'Remove from saved' : 'Save'} onPress={() => toggleSave(id)} />
            <IconButton icon="share" label="Share" onPress={() => void Share.share({ message: `${item.title}\n${item.url}` })} />
            <IconButton icon="dots" label="More actions" onPress={() => setMenu(true)} />
          </>
        }
      />
      <ScrollView contentContainerStyle={{ padding: space.gutter, paddingBottom: insets.bottom + space.xxl, gap: space.lg, maxWidth: 680, width: '100%', alignSelf: 'center' }}>
        {/* 2 Context strip */}
        <View style={{ gap: 6 }}>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            {sectionTag && <View style={{ backgroundColor: isMust || context === 'alert' ? c.highlight : c.surface2, paddingHorizontal: 8, paddingVertical: 3, borderRadius: radius.badge }}>
              <Txt v="label" color={isMust || context === 'alert' ? c.onHighlight : c.ink}>{sectionTag}</Txt>
            </View>}
            <Badges item={item} showSection={false} />
            <Txt v="meta" muted>{topicLabel(item.topic)}{ageLabel(item.published_at) ? `, ${ageLabel(item.published_at)}` : ''}</Txt>
          </View>
          {(item.cluster_size ?? 1) >= 2 && (
            <Txt v="meta" muted>Covered by {item.cluster_size} sources{item.first_report ? ` · first reported by ${item.source_name}` : ''}</Txt>
          )}
        </View>

        {context === 'cited' && <Txt v="meta" style={{ backgroundColor: c.surface2, padding: space.md, borderRadius: radius.card }}>Cited in your answer</Txt>}

        {/* 3 Headline */}
        <Txt v="storyHeadline" accessibilityRole="header">{item.title}</Txt>

        {/* 4 Why it matters to you */}
        <View style={{ borderRadius: radius.card, borderWidth: 1.5, borderColor: isMust ? c.highlight : c.hairline, backgroundColor: c.surface, padding: space.lg, gap: space.sm }}>
          <Txt v="metaBold">{context === 'alert' ? 'Why you got this alert' : 'Why it matters to you'}</Txt>
          {parts && (parts.kind === 'direct' || parts.kind === 'connected') ? (
            <>
              <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
                <Chip label="You" />
                <Txt v="meta" muted>→ {parts.role === 'covers' ? 'cover' : 'follow'} →</Txt>
                <Chip label={parts.seed_name ?? ''} trailing={parts.seed_weight ? <SignalBars level={parts.seed_weight} color={c.ink} dim={c.hairline} /> : undefined} />
                {parts.kind === 'connected' && (<><Txt v="meta" muted>→ often mentioned with →</Txt><Chip label={parts.via_name ?? ''} /></>)}
              </View>
              {parts.seed_weight && <Txt v="body">{importance[parts.seed_weight].label}: {importance[parts.seed_weight].outcome}</Txt>}
              {!!parts.also?.length && <Txt v="meta" muted>Also linked: {parts.also.join(', ')}</Txt>}
            </>
          ) : explanation ? (
            <Txt v="body">{explanation}</Txt>
          ) : note ? (
            <Txt v="body">{note}</Txt>
          ) : (
            <>
              <Txt v="body">You don’t follow anyone in this story.</Txt>
              <View style={{ flexDirection: 'row', gap: 6, flexWrap: 'wrap' }}>
                {item.entities?.map((e) => <Chip key={e.key} label={`Follow ${e.name}`} icon="plus" onPress={() => setEditing({ key: e.key, name: e.name, role: 'follows', weight: 2 })} />)}
              </View>
            </>
          )}
          {explanation && <Button label="Why this?" variant="text" small onPress={() => setWhy({ ...item, ...fromSlate, explanation, explanation_parts: parts })} style={{ alignSelf: 'flex-start' }} />}
        </View>

        {/* 5 Summary */}
        <View style={{ gap: 6 }}>
          <View style={{ flexDirection: 'row', alignItems: 'center' }}>
            <Txt v="label" muted style={{ flex: 1 }}>
              {limited ? '' : rendered ? `In your style: ${style ? `${cap(style.tone)} · ${cap(style.length)}` : ''}` : 'Key sentences from the article'}
            </Txt>
            {item.summary_text && <Button label={showOriginal ? 'Show your style' : 'Show original'} variant="text" small onPress={() => setShowOriginal((s) => !s)} />}
          </View>
          {detail.isLoading && !text ? <Skeleton h={80} /> : (
            <Txt v="storySummary">{rendered ? item.summary_text : long ?? (limited && text ? `${text}…` : text) ?? ''}</Txt>
          )}
          {limited && (
            <Txt v="meta" muted>{item.topic === 'other' ? 'Limited analysis: MAPNAI analyses sports and film in depth.' : 'Summary not ready yet.'}</Txt>
          )}
        </View>

        {/* 6 Impact */}
        {item.topic !== 'other' && (
          <View style={{ borderRadius: radius.card, borderWidth: 1, borderColor: c.hairline, backgroundColor: c.surface }}>
            <Pressable onPress={() => risk && setImpactOpen((o) => !o)} disabled={!risk} accessibilityRole="button" accessibilityState={{ expanded: impactOpen }}
              style={{ flexDirection: 'row', alignItems: 'center', padding: space.lg, minHeight: 52 }}>
              <Txt v="metaBold" style={{ flex: 1 }}>
                {risk ? `Impact: ${risk.level === 'ESCALATE' ? 'Major' : risk.level === 'ALERT' ? 'High impact' : 'Routine'}` : 'Impact not scored yet'}
              </Txt>
              {risk && <Txt v="meta" muted>{impactOpen ? 'Hide' : 'Show'}</Txt>}
            </Pressable>
            {!risk && <Txt v="meta" muted style={{ paddingHorizontal: space.lg, paddingBottom: space.lg, marginTop: -space.sm }}>Ranked by how widely it’s covered.</Txt>}
            {risk && impactOpen && (
              <View style={{ paddingHorizontal: space.lg, paddingBottom: space.lg, gap: 10 }}>
                {risk.reasoning && ([
                  ['How serious it is', risk.reasoning.severity],
                  ['How prominent', risk.reasoning.prominence],
                  ['How urgent', risk.reasoning.urgency],
                  ['Usual weight of news', risk.reasoning.base_weight],
                ] as const).map(([label, v]) => (
                  // Relative bars, unlabelled on purpose: users compare factors, never see scores
                  <View key={label} style={{ flexDirection: 'row', alignItems: 'center', gap: 12 }} accessible accessibilityLabel={`${label}: ${v >= 0.75 ? 'high' : v >= 0.5 ? 'medium' : 'low'}`}>
                    <Txt v="meta" style={{ width: 150 }}>{label}</Txt>
                    <View style={{ flex: 1, height: 8, borderRadius: 4, backgroundColor: c.surface2 }}>
                      <View style={{ width: `${Math.round(v * 100)}%`, height: 8, borderRadius: 4, backgroundColor: c.ink }} />
                    </View>
                  </View>
                ))}
                <Txt v="meta" muted>Coverage: {item.cluster_size} sources{item.first_report ? ', first report' : ''}</Txt>
                {risk.action_recommendation && (
                  <Txt v="meta" muted>AI suggestion from MAPNAI’s risk agent. May be wrong: {risk.action_recommendation}</Txt>
                )}
              </View>
            )}
          </View>
        )}

        {/* 7 People and teams */}
        {!!item.entities?.length && (
          <View style={{ gap: 8 }}>
            <Txt v="metaBold">People and teams</Txt>
            <View style={{ flexDirection: 'row', gap: 8, flexWrap: 'wrap' }}>
              {item.entities.map((e) => {
                const f = followOf(profile.data, e.key);
                return (
                  <Chip key={e.key} label={e.name}
                    trailing={f ? <SignalBars level={f.weight} color={c.ink} dim={c.hairline} /> : <Txt v="metaBold">+</Txt>}
                    onPress={() => router.push({ pathname: '/entity/[key]', params: { key: e.key } })} />
                );
              })}
            </View>
          </View>
        )}

        {/* 8 Other angles */}
        {(item.cluster_size ?? 1) >= 2 && (
          <View style={{ borderRadius: radius.card, borderWidth: 1, borderColor: c.hairline, padding: space.lg, gap: 4 }}>
            {item.another_angle && (
              <Pressable onPress={() => openOriginal(item.another_angle!.url)} accessibilityRole="link">
                <Txt v="metaBold">Another angle{item.another_angle.source_name ? ` from ${item.another_angle.source_name}` : ''}</Txt>
              </Pressable>
            )}
            <Button label={`See all ${item.cluster_size} sources`} variant="text" small onPress={() => router.push({ pathname: '/sources/[id]', params: { id } })} style={{ alignSelf: 'flex-start' }} />
          </View>
        )}

        {/* 9 Read the full article */}
        <Button label={`Read at ${item.source_name ?? 'source'}`} variant="secondary" onPress={() => openOriginal(item.url)} />

        {/* 10 Related */}
        {!!detail.data?.related?.length && (
          <View>
            <SectionTitle title="Related stories" />
            {detail.data.related.map((r) => (
              <Pressable key={r.article_id} onPress={() => openStory(r, 'deeplink')} accessibilityRole="button"
                style={{ paddingVertical: 12, borderBottomWidth: 1, borderBottomColor: c.hairline }}>
                <Txt v="compactHeadline">{r.title}</Txt>
                <Txt v="meta" muted>{topicLabel(r.topic)}{ageLabel(r.published_at) ? `, ${ageLabel(r.published_at)}` : ''}</Txt>
              </Pressable>
            ))}
          </View>
        )}

        {/* 11 Feedback */}
        <View style={{ gap: space.md }}>
          {(isMust || context === 'alert') && (
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
              <Txt v="metaBold" style={{ flex: 1 }}>{context === 'alert' ? 'Was this alert worth it?' : 'Did you need this?'}</Txt>
              <Chip label="Yes" selected={cal === 'needed'} onPress={() => calibrate(id, 'needed')} />
              <Chip label="No" selected={cal === 'not_needed'} onPress={() => calibrate(id, 'not_needed')} />
            </View>
          )}
          <View style={{ flexDirection: 'row', gap: 8 }}>
            <Button label="More like this" variant={reaction === 'more' ? 'primary' : 'secondary'} small style={{ flex: 1 }} onPress={() => react(id, 'more')} />
            <Button label="Less like this" variant={reaction === 'less' ? 'primary' : 'secondary'} small style={{ flex: 1 }} onPress={() => react(id, 'less')} />
          </View>
        </View>

        {/* 12 Ask about this */}
        <Button label="Ask about this story" variant="highlight" icon="ask"
          onPress={() => router.push({ pathname: '/ask', params: { article: id, title: item.title } })} />
      </ScrollView>

      <WhySheet item={why} onClose={() => setWhy(null)} />
      <Sheet visible={menu} onClose={() => setMenu(false)} title="More">
        {!isMust && <Button label="I needed this earlier" variant="secondary" onPress={() => { setMenu(false); calibrate(id, 'missed'); }} />}
        <Button label="Open original" variant="secondary" onPress={() => { setMenu(false); void openOriginal(item.url); }} />
        <Button label="Report a problem" variant="secondary" onPress={() => { setMenu(false); router.push('/settings/help'); }} />
      </Sheet>
      <ConnectionSheet value={editing} onClose={() => setEditing(null)} saving={follow.isPending}
        onSave={(conn) => follow.mutate({ upsert: [{ key: conn.key, role: conn.role, weight: conn.weight }] }, {
          onSuccess: () => { setEditing(null); useFeedback.getState().showToast(`Following ${conn.name} · ${importance[conn.weight].label}`); },
        })} />
      <StylePrompt visible={stylePrompt} onClose={() => setStylePrompt(false)} />
    </View>
  );
}

const cap = (s: string) => s[0].toUpperCase() + s.slice(1);

// X3 Style prompt: asked once, after the third story is opened
function StylePrompt({ visible, onClose }: { visible: boolean; onClose: () => void }) {
  const uid = useUserId();
  const ctx = useSession((s) => s.context);
  const [tone, setTone] = useState<'plain' | 'analyst'>(ctx.includes('cover') ? 'analyst' : 'plain');
  const [length, setLength] = useState<'short' | 'medium'>('short');
  return (
    <Sheet visible={visible} onClose={onClose} title="How should summaries read?">
      <Txt v="body" muted>You can change this anytime in Profile.</Txt>
      <Segmented label="Tone" value={tone} onChange={setTone} options={[{ label: 'Plain', value: 'plain' }, { label: 'Analyst', value: 'analyst' }]} />
      <Segmented label="Length" value={length} onChange={setLength} options={[{ label: 'Short', value: 'short' }, { label: 'Medium', value: 'medium' }]} />
      <Button label="Save" onPress={() => { void api.patchStyle(uid, { tone, length }).catch(() => {}); onClose(); }} />
      <Button label="Not now" variant="text" onPress={onClose} />
    </Sheet>
  );
}
