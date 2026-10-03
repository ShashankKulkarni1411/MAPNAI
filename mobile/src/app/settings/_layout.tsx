import { Stack } from 'expo-router';

import { useTheme } from '@/theme/useTheme';

export default function SettingsStack() {
  const { c } = useTheme();
  return <Stack screenOptions={{ headerShown: false, contentStyle: { backgroundColor: c.bg } }} />;
}
