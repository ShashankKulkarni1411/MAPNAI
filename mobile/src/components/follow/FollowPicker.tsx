// Shared by O4 Follow and P4 Add follows: debounced entity search, suggestion chips and a "Following (n)" tray.
// Entity types are never shown (they're unreliable); results show "In N stories".
import { useEffect, useState } from 'react';
import { Pressable, TextInput, View } from 'react-native';
import { useQuery } from '@tanstack/react-query';

import { api } from '@/api/endpoints';
import type { EntityHit, Role, WeightLevel } from '@/api/types';
import { importance } from '@/lib/labels';
import { fonts, radius, space } from '@/theme/tokens';
import { useTheme } from '@/theme/useTheme';
import { Glyph, SignalBars } from '../Glyph';
import { Txt } from '../Txt';
import { Chip, InlineError, SectionTitle, Skeleton } from '../ui';
import { Connection, ConnectionSheet } from './ConnectionSheet';

export const SOFT_CAP = 30;

function useDebounced<T>(v: T, ms = 250) {
  const [d, setD] = useState(v);
  useEffect(() => {
    const t = setTimeout(() => setD(v), ms);
    return () => clearTimeout(t);
  }, [v, ms]);
  return d;
}

type Props = {
  tray: Connection[];
  setTray: (t: Connection[]) => void;
  defaultRole: Role;
  suggestions: { title: string; items: { key: string; name: string }[] }[];
};

export function FollowPicker({ tray, setTray, defaultRole, suggestions }: Props) {
  const { c } = useTheme();
  const [q, setQ] = useState('');
  const dq = useDebounced(q.trim());
  const [editing, setEditing] = useState<Connection | null>(null);
  const results = useQuery({ queryKey: ['entities', dq], queryFn: () => api.searchEntities(dq), enabled: dq.length >= 2 });

  const has = (key: string) => tray.some((t) => t.key === key);
  const add = (e: { key: string; name: string }) => {
    if (has(e.key) || tray.length >= SOFT_CAP) return; // duplicates merge
    setTray([...tray, { key: e.key, name: e.name, role: defaultRole, weight: 2 }]);
  };

  return (
    <View style={{ gap: space.md }}>
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8, borderWidth: 1.5, borderColor: c.hairline, borderRadius: radius.button, backgroundColor: c.surface, paddingHorizontal: 12 }}>
        <Glyph name="search" color={c.ink2} />
        <TextInput value={q} onChangeText={setQ} placeholder="Search teams, players, films, people…" placeholderTextColor={c.ink2}
          accessibilityLabel="Search teams, players, films, people" autoCorrect={false}
          style={{ flex: 1, minHeight: 48, color: c.ink, fontFamily: fonts.body400, fontSize: 16 }} />
        {results.isFetching && <Skeleton h={10} w={24} />}
      </View>

      {dq.length >= 2 && (
        <View>
          {results.isError && <InlineError text="Search isn’t available right now." onRetry={() => results.refetch()} />}
          {results.data?.length === 0 && <Txt v="meta" muted>Not in recent news. Try another spelling or something related.</Txt>}
          {results.data?.map((e: EntityHit) => (
            <Pressable key={e.key} onPress={() => add(e)} accessibilityRole="button" accessibilityLabel={`${e.name}, in ${e.mention_count} stories${has(e.key) ? ', added' : ''}`}
              style={{ minHeight: 52, flexDirection: 'row', alignItems: 'center', borderBottomWidth: 1, borderBottomColor: c.hairline, gap: 12 }}>
              <View style={{ flex: 1 }}>
                <Txt v="body">{e.name}</Txt>
                <Txt v="meta" muted tabular>In {e.mention_count} stories</Txt>
              </View>
              <Glyph name={has(e.key) ? 'check' : 'plus'} color={c.ink} />
            </Pressable>
          ))}
        </View>
      )}

      {suggestions.filter((s) => s.items.length).map((s) => (
        <View key={s.title} style={{ gap: 8 }}>
          <Txt v="metaBold" muted>{s.title}</Txt>
          <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8 }}>
            {s.items.map((e) => (
              <Chip key={e.key} label={e.name} selected={has(e.key)} icon={has(e.key) ? 'check' : 'plus'} onPress={() => add(e)} />
            ))}
          </View>
        </View>
      ))}

      {tray.length > 0 && (
        <View>
          <SectionTitle title={`Following (${tray.length})`} sub={tray.length >= SOFT_CAP ? 'That’s the limit for now.' : 'Tap one to change how you’re connected.'} />
          {tray.map((t) => (
            <View key={t.key} style={{ flexDirection: 'row', alignItems: 'center', minHeight: 52, borderBottomWidth: 1, borderBottomColor: c.hairline }}>
              <Pressable onPress={() => setEditing(t)} accessibilityRole="button" accessibilityHint="Edit connection" style={{ flex: 1, paddingVertical: 8 }}>
                <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
                  <Txt v="body">{t.name}</Txt>
                  <SignalBars level={t.weight} color={c.ink} dim={c.hairline} />
                </View>
                <Txt v="meta" muted>{importance[t.weight].label}</Txt>
              </Pressable>
              <Pressable onPress={() => setTray(tray.filter((x) => x.key !== t.key))} accessibilityRole="button" accessibilityLabel={`Remove ${t.name}`} hitSlop={8}
                style={{ width: 44, height: 44, alignItems: 'center', justifyContent: 'center' }}>
                <Glyph name="close" color={c.ink2} />
              </Pressable>
            </View>
          ))}
        </View>
      )}

      <ConnectionSheet
        value={editing}
        onClose={() => setEditing(null)}
        onSave={(conn) => { setTray(tray.map((t) => (t.key === conn.key ? conn : t))); setEditing(null); }}
        onRemove={(conn) => { setTray(tray.filter((t) => t.key !== conn.key)); setEditing(null); }}
      />
    </View>
  );
}

export const CONTEXT_ROLE: Record<string, Role> = { fan: 'follows', fantasy: 'follows', cover: 'covers', work: 'operates_in', invest: 'owns' };

export function defaultRoleFor(ctx: string[]): Role {
  for (const k of ['cover', 'work', 'invest']) if (ctx.includes(k)) return CONTEXT_ROLE[k];
  return 'follows';
}

export type { WeightLevel };
