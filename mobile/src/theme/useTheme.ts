import { createContext, createElement, ReactNode, useContext } from 'react';
import { useColorScheme } from 'react-native';

import { usePrefs } from '@/state/prefs';
import { dark, light, Palette } from './tokens';

// A subtree (Flash, which is "always dark" by default) can force the dark palette for everything inside it.
const ForceDark = createContext(false);

export function ForceDarkProvider({ value, children }: { value: boolean; children: ReactNode }) {
  return createElement(ForceDark.Provider, { value }, children);
}

export function useTheme(opts?: { forceDark?: boolean }): { c: Palette; isDark: boolean } {
  const system = useColorScheme();
  const choice = usePrefs((s) => s.theme);
  const forced = useContext(ForceDark);
  const isDark = forced || opts?.forceDark || (choice === 'system' ? system === 'dark' : choice === 'dark');
  return { c: isDark ? dark : light, isDark };
}
