import { Stack } from 'expo-router';

import { useTheme } from '@/theme/useTheme';

export default function ProfileStack() {
  const { c } = useTheme();
  return <Stack screenOptions={{ headerShown: false, contentStyle: { backgroundColor: c.bg } }} />;
}
