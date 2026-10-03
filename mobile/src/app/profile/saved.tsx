// P9 Saved. GET /v1/users/{id}/saved is Proposed (mock derives it from save/unsave feedback).
import { useQuery } from '@tanstack/react-query';
import { FlatList, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { api } from '@/api/endpoints';
import { useUserId } from '@/api/hooks';
import { StoryCard } from '@/components/story/StoryCard';
import { Button } from '@/components/Button';
import { CardSkeleton, EmptyState, TopBar } from '@/components/ui';
import { toggleSave, useFeedback } from '@/state/feedback';
import { space } from '@/theme/tokens';
import { useTheme } from '@/theme/useTheme';

export default function Saved() {
  const { c } = useTheme();
  const insets = useSafeAreaInsets();
  const uid = useUserId();
  const q = useQuery({ queryKey: ['saved', uid], queryFn: () => api.saved(uid), enabled: !!uid });
  const unsaved = useFeedback((s) => s.saved);
  const items = (q.data ?? []).filter((i) => unsaved[i.article_id] !== false);
  return (
    <View style={{ flex: 1, backgroundColor: c.bg, paddingTop: insets.top }}>
      <TopBar title="Saved" />
      <FlatList
        data={items}
        keyExtractor={(i) => i.article_id}
        contentContainerStyle={{ padding: space.gutter, paddingBottom: insets.bottom + space.xl }}
        ListHeaderComponent={q.isLoading ? <CardSkeleton /> : null}
        ListEmptyComponent={q.isLoading ? null : <EmptyState text="Save stories to read later. They're kept offline too." />}
        renderItem={({ item }) => (
          <View>
            <StoryCard item={item} variant="compact" context="deeplink" />
            <Button label="Remove" variant="text" small style={{ alignSelf: 'flex-end', marginTop: -space.sm }} onPress={() => toggleSave(item.article_id)} />
          </View>
        )}
      />
    </View>
  );
}
