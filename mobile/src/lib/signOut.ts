// Sign out clears tokens, the cached brief, Ask history and the session (spec §6). Device prefs stay.
import AsyncStorage from '@react-native-async-storage/async-storage';
import { router } from 'expo-router';

import { queryClient } from '@/api/hooks';
import { flushAll } from '@/state/feedback';
import { useAskHistory } from '@/state/askHistory';
import { useSession } from '@/state/session';

export function signOutEverywhere() {
  flushAll();
  useAskHistory.getState().clear();
  queryClient.clear();
  void AsyncStorage.multiRemove(['mapnai.digest', 'mapnai.alertsRead', 'mapnai.recentSearches']).catch(() => {});
  useSession.getState().signOut();
  router.replace('/(auth)/welcome');
}
