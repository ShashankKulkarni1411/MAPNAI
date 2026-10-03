// K1 Ask MAPNAI: answers only from collected stories, always with sources, or says plainly it can't.
// UI hallucination guards: no answer card without at least one source; unmapped citation markers are dropped.
import { router, useLocalSearchParams } from 'expo-router';
import { useEffect, useMemo, useRef, useState } from 'react';
import { AccessibilityInfo, KeyboardAvoidingView, Platform, Pressable, ScrollView, TextInput, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import * as Clipboard from 'expo-clipboard';

import { api } from '@/api/endpoints';
import { useDigest, useProfile } from '@/api/hooks';
import type { AskAnswer } from '@/api/types';
import { Button } from '@/components/Button';
import { Glyph } from '@/components/Glyph';
import { Txt } from '@/components/Txt';
import { Chip, IconButton, InlineError } from '@/components/ui';
import { topicLabel } from '@/lib/labels';
import { ageLabel } from '@/lib/time';
import { useAskHistory } from '@/state/askHistory';
import { usePrefs } from '@/state/prefs';
import { useStoryCache } from '@/state/storyCache';
import { fonts, radius, space } from '@/theme/tokens';
import { useTheme } from '@/theme/useTheme';

type Turn = { q: string; state: 'searching' | 'reading' | 'writing' | 'done' | 'error'; answer?: AskAnswer };

const SCOPE_HINT = 'MAPNAI answers from news it has collected. It doesn’t predict results or give betting advice.';

export default function Ask() {
  const { c } = useTheme();
  const insets = useSafeAreaInsets();
  const params = useLocalSearchParams<{ article?: string; title?: string; q?: string }>();
  const [contextArticle, setContextArticle] = useState(params.article ? { id: params.article, title: params.title ?? '' } : null);
  const [domain, setDomain] = useState<string | undefined>();
  const [text, setText] = useState(params.q ?? '');
  const [turns, setTurns] = useState<Turn[]>([]);
  const [showHistory, setShowHistory] = useState(false);
  const history = useAskHistory();
  const seenTips = usePrefs((s) => s.seenTips);
  const markTip = usePrefs((s) => s.markTip);
  const digest = useDigest();
  const profile = useProfile();
  const scroll = useRef<ScrollView>(null);
  const busy = turns.some((t) => t.state !== 'done' && t.state !== 'error');

  // Suggested questions, built on the device from must-knows and follows
  const suggestions = useMemo(() => {
    const out: string[] = [];
    digest.data?.items.filter((i) => i.section === 'must_know').slice(0, 2).forEach((i) => {
      const e = i.entities?.[0]?.name;
      if (e) out.push(`What's the latest on ${e}?`);
    });
    profile.data?.exposures.slice(0, 2).forEach((e) => out.push(`Why is ${e.name} in the news?`));
    if (out.length < 4) out.push('Who won the Japanese Grand Prix?');
    return [...new Set(out)].slice(0, 4);
  }, [digest.data, profile.data]);

  async function send(raw = text) {
    const q = raw.trim().slice(0, 300);
    if (!q || busy) return;
    setText('');
    const idx = turns.length;
    const setState = (p: Partial<Turn>) => setTurns((ts) => ts.map((t, i) => (i === idx ? { ...t, ...p } : t)));
    setTurns((ts) => [...ts, { q, state: 'searching' }]);
    // Honest staged status; the real API returns everything at once
    const t1 = setTimeout(() => setState({ state: 'reading' }), 600);
    const t2 = setTimeout(() => setState({ state: 'writing' }), 1300);
    try {
      const answer = await Promise.race([
        api.ask(q, domain, contextArticle?.id),
        new Promise<never>((_, rej) => setTimeout(() => rej(new Error('timeout')), 20_000)),
      ]);
      setState({ state: 'done', answer });
      history.add({ id: `${Date.now()}`, at: new Date().toISOString(), domain, answer });
      AccessibilityInfo.announceForAccessibility(answer.answer && answer.sources.length ? 'Answer ready' : "Couldn't find stories about this");
    } catch {
      setState({ state: 'error' });
    } finally {
      clearTimeout(t1);
      clearTimeout(t2);
      setTimeout(() => scroll.current?.scrollToEnd({ animated: true }), 50);
    }
  }

  useEffect(() => {
    if (params.q) void send(params.q);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (showHistory) return <History onClose={() => setShowHistory(false)} onPick={(a) => { setTurns([{ q: a.query, state: 'done', answer: a }]); setShowHistory(false); }} />;

  return (
    <KeyboardAvoidingView style={{ flex: 1, backgroundColor: c.bg }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <View style={{ flexDirection: 'row', alignItems: 'center', paddingTop: Platform.OS === 'android' ? insets.top : space.sm, paddingHorizontal: space.sm, borderBottomWidth: 1, borderBottomColor: c.hairline }}>
        <Txt v="sectionTitle" accessibilityRole="header" style={{ flex: 1, paddingLeft: space.sm }}>Ask MAPNAI</Txt>
        <Button label="Recent" variant="text" small onPress={() => setShowHistory(true)} />
        <IconButton icon="close" label="Close" onPress={() => router.back()} />
      </View>

      <ScrollView ref={scroll} keyboardShouldPersistTaps="handled" contentContainerStyle={{ padding: space.gutter, gap: space.lg, maxWidth: 680, width: '100%', alignSelf: 'center' }}>
        {turns.length === 0 && (
          <>
            <Txt v="body" muted>Answers from the news MAPNAI has collected, with sources.</Txt>
            {!seenTips.ask && (
              <Pressable onPress={() => markTip('ask')} accessibilityHint="Dismiss" style={{ padding: space.md, borderRadius: radius.card, backgroundColor: c.surface2 }}>
                <Txt v="meta">I answer from collected sports and film news, with sources. I can’t browse the web or predict results.</Txt>
              </Pressable>
            )}
            <View style={{ gap: 8 }}>
              {suggestions.map((s) => (
                <Pressable key={s} onPress={() => send(s)} accessibilityRole="button"
                  style={{ padding: space.md, borderRadius: radius.card, borderWidth: 1, borderColor: c.hairline, backgroundColor: c.surface }}>
                  <Txt v="body">{s}</Txt>
                </Pressable>
              ))}
            </View>
          </>
        )}
        {turns.map((t, i) => <TurnView key={i} turn={t} onRetry={() => send(t.q)} onFollowUp={send} />)}
      </ScrollView>

      <View style={{ borderTopWidth: 1, borderTopColor: c.hairline, padding: space.md, paddingBottom: insets.bottom + space.md, gap: 8 }}>
        <View style={{ flexDirection: 'row', gap: 8, flexWrap: 'wrap' }}>
          {[['All', undefined], ['Sports', 'sports'], ['Film', 'entertainment_movies']].map(([l, v]) => (
            <Chip key={l} label={l!} selected={domain === v} onPress={() => setDomain(v)} />
          ))}
          {contextArticle && (
            <Chip label={`About: ${contextArticle.title.slice(0, 32)}${contextArticle.title.length > 32 ? '…' : ''}`} icon="close"
              accessibilityHint="Removes the story context" onPress={() => setContextArticle(null)} />
          )}
        </View>
        <View style={{ flexDirection: 'row', alignItems: 'flex-end', gap: 8 }}>
          <TextInput value={text} onChangeText={setText} placeholder="Ask about sports or film news" placeholderTextColor={c.ink2}
            multiline maxLength={300} accessibilityLabel="Your question"
            style={{ flex: 1, minHeight: 48, maxHeight: 120, borderWidth: 1.5, borderColor: c.hairline, borderRadius: radius.button, paddingHorizontal: 14, paddingVertical: 12, color: c.ink, fontFamily: fonts.body400, fontSize: 16, backgroundColor: c.surface }} />
          <Pressable onPress={() => send()} disabled={busy || !text.trim()} accessibilityRole="button" accessibilityLabel="Send"
            style={{ width: 48, height: 48, borderRadius: radius.button, backgroundColor: c.ink, alignItems: 'center', justifyContent: 'center', opacity: busy || !text.trim() ? 0.4 : 1 }}>
            <Glyph name="skip" color={c.bg} />
          </Pressable>
        </View>
      </View>
    </KeyboardAvoidingView>
  );
}

function strength(conf: number) {
  if (conf >= 0.7) return 'Strong match';
  if (conf >= 0.4) return 'Partial match';
  return 'Weak match';
}

function TurnView({ turn, onRetry, onFollowUp }: { turn: Turn; onRetry: () => void; onFollowUp: (q: string) => void }) {
  const { c } = useTheme();
  const put = useStoryCache((s) => s.put);
  const a = turn.answer;
  const status = { searching: 'Searching stories…', reading: 'Reading 5 stories…', writing: 'Writing the answer…' } as const;

  const body = (() => {
    if (turn.state === 'error') return <InlineError text="Couldn’t get an answer. Try again." onRetry={onRetry} />;
    if (turn.state !== 'done' || !a) return <Txt v="meta" muted accessibilityLiveRegion="polite">{status[turn.state as keyof typeof status]}</Txt>;
    // No-result card: no sources, even if text exists
    if (!a.sources.length || !a.answer) {
      return (
        <View style={{ gap: 8, padding: space.lg, borderRadius: radius.card, backgroundColor: c.surface, borderWidth: 1, borderColor: c.hairline }}>
          <Txt v="body">I couldn’t find stories about this yet.</Txt>
          <Txt v="meta" muted>{SCOPE_HINT}</Txt>
          <Button label="Search instead" variant="secondary" small style={{ alignSelf: 'flex-start' }}
            onPress={() => router.push('/search')} />
        </View>
      );
    }
    // Citations: "Source Article i" or [n] → markers; drop markers that don't map to a listed source
    const text = a.answer
      .replace(/Source Article (\d+)/g, '[$1]')
      .replace(/\[(\d+)\]/g, (m, n) => (Number(n) >= 1 && Number(n) <= a.sources.length ? `[${n}]` : ''));
    const openSource = (i: number) => {
      const s = a.sources[i];
      put({ item: { article_id: s.article_id, title: s.title, url: '', topic: s.domain ?? 'other', source_name: s.source_name, published_at: s.published_at }, context: 'cited', note: text });
      router.push({ pathname: '/story/[id]', params: { id: s.article_id, ctx: 'cited' } });
    };
    const topEntity = a.sources[0]?.title.split(' ').slice(0, 2).join(' ');
    return (
      <View style={{ gap: space.md, padding: space.lg, borderRadius: radius.card, backgroundColor: c.surface, borderWidth: 1, borderColor: c.hairline }}>
        <Txt v="summary">
          {text.split(/(\[\d+\])/).map((part, i) => {
            const m = part.match(/^\[(\d+)\]$/);
            return m
              ? <Txt key={i} v="metaBold" onPress={() => openSource(Number(m[1]) - 1)} accessibilityRole="link" accessibilityLabel={`Source ${m[1]}`} style={{ textDecorationLine: 'underline' }}>{part}</Txt>
              : part;
          })}
        </Txt>
        <Txt v="metaBold">Based on {a.sources.length} stor{a.sources.length === 1 ? 'y' : 'ies'} · {strength(a.confidence)}</Txt>
        {a.confidence < 0.4 && <Txt v="meta" muted>The sources may not fully answer this.</Txt>}
        {a.sources.map((s, i) => (
          <Pressable key={s.article_id} onPress={() => openSource(i)} accessibilityRole="button"
            style={{ flexDirection: 'row', gap: 10, paddingVertical: 8, borderTopWidth: 1, borderTopColor: c.hairline }}>
            <Txt v="metaBold" tabular>{i + 1}</Txt>
            <View style={{ flex: 1 }}>
              <Txt v="body">{s.title}</Txt>
              <Txt v="meta" muted>{[s.source_name, ageLabel(s.published_at), topicLabel(s.domain)].filter(Boolean).join(', ')}</Txt>
            </View>
          </Pressable>
        ))}
        <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8 }}>
          {topEntity && <Chip label={`More about ${topEntity}`} onPress={() => onFollowUp(`More about ${topEntity}`)} />}
          <Chip label="Search stories" onPress={() => router.push('/search')} />
        </View>
        <View style={{ flexDirection: 'row', gap: 8 }}>
          <Button label="Copy" variant="text" small onPress={() => void Clipboard.setStringAsync(text)} />
        </View>
      </View>
    );
  })();

  return (
    <View style={{ gap: 8 }}>
      <View style={{ alignSelf: 'flex-end', maxWidth: '85%', backgroundColor: c.ink, borderRadius: radius.card, padding: space.md }}>
        <Txt v="body" color={c.bg}>{turn.q}</Txt>
      </View>
      {body}
    </View>
  );
}

function History({ onClose, onPick }: { onClose: () => void; onPick: (a: AskAnswer) => void }) {
  const { c } = useTheme();
  const insets = useSafeAreaInsets();
  const { turns, clear } = useAskHistory();
  return (
    <View style={{ flex: 1, backgroundColor: c.bg, paddingTop: Platform.OS === 'android' ? insets.top : 0 }}>
      <View style={{ flexDirection: 'row', alignItems: 'center', paddingHorizontal: space.sm, borderBottomWidth: 1, borderBottomColor: c.hairline }}>
        <IconButton icon="back" label="Back" onPress={onClose} />
        <Txt v="sectionTitle" style={{ flex: 1 }}>Recent questions</Txt>
        {turns.length > 0 && <Button label="Clear history" variant="text" small onPress={clear} />}
      </View>
      <ScrollView contentContainerStyle={{ padding: space.gutter }}>
        {turns.length === 0 && <Txt v="body" muted>Questions you ask appear here. They stay on this device.</Txt>}
        {turns.map((t) => (
          <Pressable key={t.id} onPress={() => onPick(t.answer)} accessibilityRole="button" style={{ paddingVertical: 12, borderBottomWidth: 1, borderBottomColor: c.hairline }}>
            <Txt v="body">{t.answer.query}</Txt>
            <Txt v="meta" muted>{new Date(t.at).toLocaleString()}</Txt>
          </Pressable>
        ))}
      </ScrollView>
    </View>
  );
}
