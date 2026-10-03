// Device-only appearance and comfort settings (spec §17 T5). Never synced to the server.
import AsyncStorage from '@react-native-async-storage/async-storage';
import { create } from 'zustand';
import { createJSONStorage, persist } from 'zustand/middleware';

export type ThemeChoice = 'system' | 'light' | 'dark';

type PrefsState = {
  theme: ThemeChoice;
  flashAlwaysDark: boolean;
  haptics: boolean;
  reduceMotionOverride: boolean | null; // null = follow the system
  seenTips: Record<string, boolean>;
  setTheme: (t: ThemeChoice) => void;
  setFlashAlwaysDark: (v: boolean) => void;
  setHaptics: (v: boolean) => void;
  markTip: (id: string) => void;
};

export const usePrefs = create<PrefsState>()(
  persist(
    (set) => ({
      theme: 'system',
      flashAlwaysDark: true,
      haptics: true,
      reduceMotionOverride: null,
      seenTips: {},
      setTheme: (theme) => set({ theme }),
      setFlashAlwaysDark: (flashAlwaysDark) => set({ flashAlwaysDark }),
      setHaptics: (haptics) => set({ haptics }),
      markTip: (id) => set((s) => ({ seenTips: { ...s.seenTips, [id]: true } })),
    }),
    { name: 'mapnai.prefs', storage: createJSONStorage(() => AsyncStorage) },
  ),
);
