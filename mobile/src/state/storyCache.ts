// The card that opened a story hands its data to S1 so the headline and context show instantly (spec S1 loading).
import { create } from 'zustand';

import type { StoryItem } from '@/api/types';

export type EntryContext = 'slate' | 'search' | 'alert' | 'developing' | 'cited' | 'recap' | 'deeplink';

type Entry = { item: StoryItem; context: EntryContext; note?: string };

type S = { entries: Record<string, Entry>; put: (e: Entry) => void; opened: Record<string, true>; markOpened: (id: string) => void };

export const useStoryCache = create<S>()((set) => ({
  entries: {},
  opened: {},
  put: (e) => set((s) => ({ entries: { ...s.entries, [e.item.article_id]: e } })),
  markOpened: (id) => set((s) => ({ opened: { ...s.opened, [id]: true } })),
}));
