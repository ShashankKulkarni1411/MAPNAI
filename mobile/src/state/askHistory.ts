// K2 Ask history: on the device only, last 50 questions. Cleared on sign-out.
import AsyncStorage from '@react-native-async-storage/async-storage';
import { create } from 'zustand';
import { createJSONStorage, persist } from 'zustand/middleware';

import type { AskAnswer } from '@/api/types';

export type AskTurn = { id: string; at: string; domain?: string; answer: AskAnswer };

type S = { turns: AskTurn[]; add: (t: AskTurn) => void; clear: () => void };

export const useAskHistory = create<S>()(
  persist(
    (set) => ({
      turns: [],
      add: (t) => set((s) => ({ turns: [t, ...s.turns].slice(0, 50) })),
      clear: () => set({ turns: [] }),
    }),
    { name: 'mapnai.ask', storage: createJSONStorage(() => AsyncStorage) },
  ),
);
