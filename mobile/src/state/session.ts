// Session and onboarding progress. Tokens live in expo-secure-store (AsyncStorage on web, which has no secure store).
import AsyncStorage from '@react-native-async-storage/async-storage';
import * as SecureStore from 'expo-secure-store';
import { Platform } from 'react-native';
import { create } from 'zustand';
import { createJSONStorage, persist, StateStorage } from 'zustand/middleware';

const secure: StateStorage =
  Platform.OS === 'web'
    ? AsyncStorage
    : {
        getItem: (k) => SecureStore.getItemAsync(k),
        setItem: (k, v) => SecureStore.setItemAsync(k, v),
        removeItem: (k) => SecureStore.deleteItemAsync(k),
      };

// Order matters: resume at the first incomplete step (spec §7 "save as you go")
export const ONBOARDING_STEPS = ['about', 'connected', 'swipe', 'follow', 'alerts', 'building', 'done'] as const;
export type OnboardingStep = (typeof ONBOARDING_STEPS)[number];

export type Context = 'fan' | 'cover' | 'fantasy' | 'work' | 'invest';

type SessionState = {
  hydrated: boolean;
  accessToken: string | null;
  refreshToken: string | null;
  email: string | null;
  emailVerified: boolean;
  birthYear: number | null;
  userId: string | null; // engine user_id from POST /v1/users
  name: string | null;
  gender: string | null; // kept on the device until PATCH demographics exists (Proposed)
  useDemographics: boolean | null;
  onboarding: OnboardingStep;
  context: Context[]; // kept on the device until personas.context exists (Proposed)
  swipes: { likes: string[]; dislikes: string[]; likedEntities: { key: string; name: string }[] };
  storiesOpened: number; // drives the X3 style prompt after the third story
  lastSeenAt: string | null;
  set: (p: Partial<SessionState>) => void;
  advance: (to: OnboardingStep) => void;
  signOut: () => void;
};

const blank = {
  accessToken: null,
  refreshToken: null,
  email: null,
  emailVerified: false,
  birthYear: null,
  userId: null,
  name: null,
  gender: null as string | null,
  useDemographics: null as boolean | null,
  onboarding: 'about' as OnboardingStep,
  context: [] as Context[],
  swipes: { likes: [], dislikes: [], likedEntities: [] },
  storiesOpened: 0,
  lastSeenAt: null,
};

export const useSession = create<SessionState>()(
  persist(
    (set, get) => ({
      hydrated: false,
      ...blank,
      set: (p) => set(p),
      advance: (to) => {
        const cur = ONBOARDING_STEPS.indexOf(get().onboarding);
        if (ONBOARDING_STEPS.indexOf(to) > cur) set({ onboarding: to });
      },
      signOut: () => set({ ...blank }),
    }),
    {
      name: 'mapnai.session',
      storage: createJSONStorage(() => secure),
      partialize: ({ hydrated, set, advance, signOut, ...rest }) => rest,
      onRehydrateStorage: () => () => useSession.setState({ hydrated: true }),
    },
  ),
);

export function onboardingRoute(step: OnboardingStep): string {
  return step === 'done' ? '/(tabs)' : `/onboarding/${step}`;
}
