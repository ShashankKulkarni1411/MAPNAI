// S2 Sources: every article in the event, with the first-report marker. Proposed GET /v1/clusters/{id}.
import { useQuery } from '@tanstack/react-query';
import { useLocalSearchParams } from 'expo-router';
import * as WebBrowser from 'expo-web-browser';
import { FlatList, Pressable, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { api } from '@/api/endpoints';
import { Txt } from '@/components/Txt';
import { CardSkeleton, InlineError, Pill, TopBar } from '@/components/ui';
import { ageLabel } from '@/lib/time';
import { implicit } from '@/state/feedback';
import { space } from '@/theme/tokens';
import { useTheme } from '@/theme/useTheme';

export default function Sources() {
  const { c } = useTheme();
  const insets = useSafeAreaInsets();
  const { id } = useLocalSearchParams<{ id: string }>();
  const q = useQuery({ queryKey: ['cluster', id], queryFn: () => api.cluster(id) });
  return (
    <View style={{ flex: 1, backgroundColor: c.bg, paddingTop: insets.top }}>
      <TopBar title={q.data ? `${q.data.length} sources` : 'Sources'} />
      {q.isLoading && <View style={{ padding: space.gutter }}><CardSkeleton /><CardSkeleton /></View>}
      {q.isError && <View style={{ padding: space.gutter }}><InlineError text="Couldn't load sources." onRetry={() => q.refetch()} /></View>}
      <FlatList
        data={q.data ?? []}
        keyExtractor={(r) => r.article_id}
        contentContainerStyle={{ padding: space.gutter, paddingBottom: insets.bottom + space.xl }}
        renderItem={({ item: r }) => (
          <Pressable accessibilityRole="link" onPress={() => { implicit(id, 'open'); void WebBrowser.openBrowserAsync(r.url); }}
            style={{ paddingVertical: 14, borderBottomWidth: 1, borderBottomColor: c.hairline, gap: 4 }}>
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
              <Txt v="metaBold">{r.source_name}</Txt>
              {ageLabel(r.published_at) && <Txt v="meta" muted>{ageLabel(r.published_at)}</Txt>}
              {r.first_report && <Pill label="First report" kind="neutral" />}
            </View>
            <Txt v="body">{r.title}</Txt>
          </Pressable>
        )}
      />
    </View>
  );
}
