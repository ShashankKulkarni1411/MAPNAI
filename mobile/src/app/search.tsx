// Q1 Search + Q2 Results. Instant retrieval, no LLM; question-like queries get an "Ask MAPNAI" hand-off.
import AsyncStorage from '@react-native-async-storage/async-storage';
import { useQuery } from '@tanstack/react-query';
import { router } from 'expo-router';
import { useEffect, useRef, useState } from 'react';
import { FlatList, Pressable, TextInput, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { api } from '@/api/endpoints';
import { followOf, useProfile } from '@/api/hooks';
import { Glyph } from '@/components/Glyph';
import { StoryCard } from '@/components/story/StoryCard';
import { Txt } from '@/components/Txt';
import { CardSkeleton, Chip, IconButton, InlineError, Segmented } from '@/components/ui';
import { fonts, radius, space } from '@/theme/tokens';
import { useTheme } from '@/theme/useTheme';

const RECENT = 'mapnai.recentSearches';
const QUESTION = /^(who|what|when|where|why|how|is|are|did|will|can)\b|\?\s*$/i;

export default function Search() {
  const { c } = useTheme();
  const insets = useSafeAreaInsets();
  const profile = useProfile();
  const [text, setText] = useState('');
  const [debounced, setDebounced] = useState('');
  const [submitted, setSubmitted] = useState<string | null>(null);
  const [seg, setSeg] = useState<'all' | 'stories' | 'people'>('all');
  const [topic, setTopic] = useState<string | undefined>(undefined);
  const [recent, setRecent] = useState<string[]>([]);
  const input = useRef<TextInput>(null);

  useEffect(() => {
    AsyncStorage.getItem(RECENT).then((r) => r && setRecent(JSON.parse(r))).catch(() => {});
  }, []);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(text.trim()), 250);
    return () => clearTimeout(t);
  }, [text]);

  const q = submitted ?? debounced;
  const entities = useQuery({ queryKey: ['entities', q], queryFn: () => api.searchEntities(q), enabled: q.length >= 2 });
  const stories = useQuery({ queryKey: ['search', q, topic], queryFn: () => api.search(q, topic), enabled: q.length >= 2 });
  const isQuestion = QUESTION.test(q);

  function submit(v = text) {
    const s = v.trim();
    if (s.length < 2) return;
    setText(s);
    setSubmitted(s);
    const next = [s, ...recent.filter((r) => r !== s)].slice(0, 10);
    setRecent(next);
    void AsyncStorage.setItem(RECENT, JSON.stringify(next)).catch(() => {});
  }
  const ask = () => router.push({ pathname: '/ask', params: { q } });

  const askRow = isQuestion && (
    <Pressable onPress={ask} accessibilityRole="button" style={{ flexDirection: 'row', alignItems: 'center', gap: 10, padding: space.md, borderRadius: radius.card, backgroundColor: c.surface2, marginBottom: space.md }}>
      <Glyph name="ask" color={c.ink} />
      <Txt v="metaBold" style={{ flex: 1 }}>Ask MAPNAI: “{q}”</Txt>
    </Pressable>
  );

  const entityRows = (entities.data ?? []).slice(0, submitted ? 10 : 5).map((e) => {
    const f = followOf(profile.data, e.key);
    return (
      <Pressable key={e.key} onPress={() => router.push({ pathname: '/entity/[key]', params: { key: e.key } })} accessibilityRole="button"
        style={{ minHeight: 52, flexDirection: 'row', alignItems: 'center', borderBottomWidth: 1, borderBottomColor: c.hairline }}>
        <View style={{ flex: 1 }}>
          <Txt v="body">{e.name}</Txt>
          <Txt v="meta" muted tabular>In {e.mention_count} stories{f ? ' · Following' : ''}</Txt>
        </View>
        <Glyph name="chevron" color={c.ink2} />
      </Pressable>
    );
  });

  return (
    <View style={{ flex: 1, backgroundColor: c.bg, paddingTop: insets.top }}>
      <View style={{ flexDirection: 'row', alignItems: 'center', paddingHorizontal: space.sm, gap: 4 }}>
        <IconButton icon="back" label="Back" onPress={() => router.back()} />
        <View style={{ flex: 1, flexDirection: 'row', alignItems: 'center', borderWidth: 1.5, borderColor: c.hairline, borderRadius: radius.button, backgroundColor: c.surface, paddingHorizontal: 12 }}>
          <Glyph name="search" color={c.ink2} />
          <TextInput ref={input} autoFocus value={text} onChangeText={(t) => { setText(t); setSubmitted(null); }} onSubmitEditing={() => submit()}
            returnKeyType="search" placeholder="Search teams, players, films, stories" placeholderTextColor={c.ink2}
            accessibilityLabel="Search teams, players, films, stories" autoCorrect={false}
            style={{ flex: 1, minHeight: 46, color: c.ink, fontFamily: fonts.body400, fontSize: 16, paddingHorizontal: 8 }} />
          {!!text && <IconButton icon="close" label="Clear search" size={18} onPress={() => { setText(''); setSubmitted(null); input.current?.focus(); }} />}
        </View>
      </View>

      {q.length < 2 ? (
        <View style={{ padding: space.gutter, gap: space.md }}>
          {recent.length > 0 && (
            <>
              <View style={{ flexDirection: 'row', alignItems: 'center' }}>
                <Txt v="metaBold" style={{ flex: 1 }}>Recent searches</Txt>
                <Pressable onPress={() => { setRecent([]); void AsyncStorage.removeItem(RECENT); }} accessibilityRole="button" hitSlop={10}>
                  <Txt v="meta" muted>Clear</Txt>
                </Pressable>
              </View>
              <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8 }}>
                {recent.map((r) => <Chip key={r} label={r} onPress={() => submit(r)} />)}
              </View>
            </>
          )}
          <Txt v="metaBold">Try</Txt>
          <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8 }}>
            {['Kohli injury', 'Jawan box office', 'Who won the Japanese Grand Prix?'].map((s) => <Chip key={s} label={s} onPress={() => submit(s)} />)}
          </View>
        </View>
      ) : !submitted ? (
        // Autocomplete: up to 5 entities, 3 headline matches, and an Ask row for questions
        <FlatList
          keyboardShouldPersistTaps="handled"
          contentContainerStyle={{ padding: space.gutter }}
          data={(stories.data?.items ?? []).slice(0, 3)}
          keyExtractor={(i) => i.article_id}
          ListHeaderComponent={<>{askRow}{entityRows}</>}
          renderItem={({ item }) => <StoryCard item={item} variant="compact" context="search" />}
        />
      ) : (
        <FlatList
          keyboardShouldPersistTaps="handled"
          contentContainerStyle={{ padding: space.gutter, paddingBottom: insets.bottom + space.xl }}
          data={seg === 'people' ? [] : stories.data?.items ?? []}
          keyExtractor={(i) => i.article_id}
          ListHeaderComponent={
            <View style={{ gap: space.md, marginBottom: space.md }}>
              <Segmented label="Result type" value={seg} onChange={setSeg}
                options={[{ label: 'All', value: 'all' }, { label: 'Stories', value: 'stories' }, { label: 'People and teams', value: 'people' }]} />
              <View style={{ flexDirection: 'row', gap: 8, flexWrap: 'wrap' }}>
                {[['All', undefined], ['Sports', 'sports'], ['Film', 'entertainment_movies'], ['General', 'other']].map(([l, v]) => (
                  <Chip key={l} label={l!} selected={topic === v} onPress={() => setTopic(v)} />
                ))}
              </View>
              {seg === 'all' && askRow}
              {seg !== 'stories' && entityRows}
              {stories.isLoading && (<><CardSkeleton /><CardSkeleton /></>)}
              {stories.isError && <InlineError text="Stories couldn’t load." onRetry={() => stories.refetch()} />}
              {stories.data?.items.length === 0 && seg !== 'people' && (
                <View style={{ gap: 6 }}>
                  <Txt v="body">No stories match ‘{q}’.</Txt>
                  <Txt v="meta" muted>Try a name or a wider time range.</Txt>
                  <Pressable onPress={ask} accessibilityRole="button"><Txt v="metaBold">Ask MAPNAI instead (it searches by meaning)</Txt></Pressable>
                </View>
              )}
            </View>
          }
          renderItem={({ item }) => <StoryCard item={item} context="search" />}
        />
      )}
    </View>
  );
}
