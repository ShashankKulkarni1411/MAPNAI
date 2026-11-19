// Push notifications (Expo push service; the server side is personalization/push.py).
// Expo Go (SDK 53+) throws as soon as expo-notifications is imported on Android and has no push on any platform, so
// the module is loaded lazily and only outside Expo Go (development / store builds). On web there is no push.
// Flow: ask permission (onboarding / settings) → this device's Expo push token → POST /v1/users/{id}/push_tokens →
// the alerts job pushes each delivered alert → tapping a notification opens its story.
import AsyncStorage from '@react-native-async-storage/async-storage';
import Constants, { ExecutionEnvironment } from 'expo-constants';
import { router } from 'expo-router';
import { useEffect } from 'react';
import { Platform } from 'react-native';

import { api } from '@/api/endpoints';

type NotificationsModule = typeof import('expo-notifications');

const TOKEN_KEY = 'mapnai.pushToken';
const CHANNEL = 'alerts'; // the channel the server's messages name (channelId)

export const inExpoGo = Constants.executionEnvironment === ExecutionEnvironment.StoreClient;
export const pushSupported = Platform.OS !== 'web' && !inExpoGo;

let mod: NotificationsModule | null = null;
function notifications(): NotificationsModule | null {
  if (!pushSupported) return null;
  if (!mod) {
    try {
      mod = require('expo-notifications') as NotificationsModule;
      mod.setNotificationHandler({
        handleNotification: async () => ({
          shouldShowBanner: true, shouldShowList: true, shouldPlaySound: true, shouldSetBadge: false,
        }),
      });
    } catch {
      return null;
    }
  }
  return mod;
}

// Android 13+ asks for the notification permission only once a channel exists
async function ensureChannel(N: NotificationsModule) {
  if (Platform.OS !== 'android') return;
  await N.setNotificationChannelAsync(CHANNEL, {
    name: 'News alerts',
    description: 'Big news about what you follow, and breaking stories',
    importance: N.AndroidImportance.HIGH,
  });
}

export async function askPushPermission(): Promise<boolean> {
  const N = notifications();
  if (!N) return false;
  try {
    await ensureChannel(N);
    const current = await N.getPermissionsAsync();
    if (current.granted) return true;
    return (await N.requestPermissionsAsync()).granted;
  } catch {
    return false;
  }
}

function projectId(): string | undefined {
  return (Constants.expoConfig?.extra as { eas?: { projectId?: string } } | undefined)?.eas?.projectId
    ?? Constants.easConfig?.projectId;
}

// Register this device for the user's alerts. Never prompts: permission is asked in onboarding or settings.
// Returns the token, or null (no permission, Expo Go, web, no EAS project id, offline).
export async function registerPush(userId: string): Promise<string | null> {
  const N = notifications();
  if (!N || !userId) return null;
  try {
    await ensureChannel(N);
    if (!(await N.getPermissionsAsync()).granted) return null;
    const { data: token } = await N.getExpoPushTokenAsync({ projectId: projectId() });
    await api.registerPushToken(userId, token, Platform.OS);
    await AsyncStorage.setItem(TOKEN_KEY, token).catch(() => {});
    return token;
  } catch {
    return null; // retried on the next launch
  }
}

// On sign-out: this device should stop receiving the user's alerts
export async function unregisterPush(userId: string | null): Promise<void> {
  const token = await AsyncStorage.getItem(TOKEN_KEY).catch(() => null);
  if (!token) return;
  await AsyncStorage.removeItem(TOKEN_KEY).catch(() => {});
  if (userId) await api.unregisterPushToken(userId, token).catch(() => {});
}

function openFrom(data: unknown) {
  const id = (data as { article_id?: unknown } | null)?.article_id;
  if (typeof id === 'string' && id) router.push({ pathname: '/story/[id]', params: { id } });
}

// Root layout: register while signed in, and open the story when a notification is tapped (also from a cold start)
export function usePush(userId: string | null) {
  useEffect(() => {
    if (userId) void registerPush(userId);
  }, [userId]);

  useEffect(() => {
    const N = notifications();
    if (!N || !userId) return;
    let handled: string | null = null;
    const open = (r: import('expo-notifications').NotificationResponse | null) => {
      if (!r || r.actionIdentifier !== N.DEFAULT_ACTION_IDENTIFIER) return;
      const key = r.notification.request.identifier;
      if (key === handled) return;
      handled = key;
      openFrom(r.notification.request.content.data);
    };
    void N.getLastNotificationResponseAsync().then(open).catch(() => {});
    const sub = N.addNotificationResponseReceivedListener(open);
    return () => sub.remove();
  }, [userId]);
}
