// Explicit feedback with a 5 s undo window (spec §23). The on-screen state changes at once; the call goes out
// when the window closes, the app backgrounds, or 10 events are pending. Implicit signals (open, dwell) skip
// the window but are deduped per story per day.
import { AccessibilityInfo, AppState } from 'react-native';
import * as Haptics from 'expo-haptics';
import { create } from 'zustand';

import { api } from '@/api/endpoints';
import type { FeedbackType } from '@/api/types';
import { isoDate } from '@/lib/time';
import { usePrefs } from './prefs';
import { useSession } from './session';

type Toast = { id: number; message: string; undo?: () => void };

type Pending = { article_id: string; type: FeedbackType; value?: number; due: number };

type FeedbackState = {
  // visible per-story state, keyed by article_id
  reaction: Record<string, 'more' | 'less' | undefined>;
  saved: Record<string, boolean>;
  calibration: Record<string, 'needed' | 'not_needed' | 'missed' | undefined>;
  hiddenToday: { day: string; keys: string[] };
  sent: Record<string, true>; // dedupe key user|article|type|day for implicit signals
  toast: Toast | null;
  pending: Record<string, Pending>; // slot key → pending event
  showToast: (message: string, undo?: () => void) => void;
  dismissToast: () => void;
};

export const useFeedback = create<FeedbackState>()((set) => ({
  reaction: {},
  saved: {},
  calibration: {},
  hiddenToday: { day: isoDate(), keys: [] },
  sent: {},
  toast: null,
  pending: {},
  showToast: (message, undo) => set({ toast: { id: Date.now(), message, undo } }),
  dismissToast: () => set({ toast: null }),
}));

let screenReader = false;
AccessibilityInfo.isScreenReaderEnabled().then((v) => (screenReader = v)).catch(() => {});
AccessibilityInfo.addEventListener?.('screenReaderChanged', (v) => (screenReader = v));
const windowMs = () => (screenReader ? 10_000 : 5_000);

const timers: Record<string, ReturnType<typeof setTimeout>> = {};

async function send(p: Pending, attempt = 0) {
  const uid = useSession.getState().userId;
  if (!uid) return;
  try {
    await api.feedback(uid, p.article_id, p.type, p.value);
  } catch {
    if (attempt < 3) setTimeout(() => send(p, attempt + 1), 1000 * 2 ** attempt);
  }
}

function flushSlot(slot: string) {
  const p = useFeedback.getState().pending[slot];
  clearTimeout(timers[slot]);
  delete timers[slot];
  if (!p) return;
  useFeedback.setState((s) => {
    const { [slot]: _, ...rest } = s.pending;
    return { pending: rest };
  });
  void send(p);
}

export function flushAll() {
  Object.keys(useFeedback.getState().pending).forEach(flushSlot);
}

AppState.addEventListener('change', (s) => {
  if (s !== 'active') flushAll();
});

function queue(slot: string, p: Omit<Pending, 'due'>) {
  clearTimeout(timers[slot]);
  useFeedback.setState((s) => ({ pending: { ...s.pending, [slot]: { ...p, due: Date.now() + windowMs() } } }));
  timers[slot] = setTimeout(() => flushSlot(slot), windowMs());
  if (Object.keys(useFeedback.getState().pending).length >= 10) flushAll();
}

function cancel(slot: string) {
  clearTimeout(timers[slot]);
  delete timers[slot];
  useFeedback.setState((s) => {
    const { [slot]: _, ...rest } = s.pending;
    return { pending: rest };
  });
}

function haptic() {
  if (usePrefs.getState().haptics) void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light).catch(() => {});
}

// More / Less share one slot per story: switching within the window replaces the pending event,
// tapping the same control again removes it.
export function react(article_id: string, kind: 'more' | 'less') {
  const slot = `${article_id}:reaction`;
  const cur = useFeedback.getState().reaction[article_id];
  haptic();
  if (cur === kind) {
    useFeedback.setState((s) => ({ reaction: { ...s.reaction, [article_id]: undefined } }));
    cancel(slot);
    return;
  }
  useFeedback.setState((s) => ({ reaction: { ...s.reaction, [article_id]: kind } }));
  queue(slot, { article_id, type: kind });
  useFeedback.getState().showToast(kind === 'more' ? "You'll see more like this" : "You'll see fewer like this", () => {
    useFeedback.setState((s) => ({ reaction: { ...s.reaction, [article_id]: cur } }));
    cancel(slot);
  });
}

export function toggleSave(article_id: string) {
  const slot = `${article_id}:save`;
  const was = !!useFeedback.getState().saved[article_id];
  haptic();
  useFeedback.setState((s) => ({ saved: { ...s.saved, [article_id]: !was } }));
  if (useFeedback.getState().pending[slot]) {
    cancel(slot); // toggled back inside the window: nothing is sent
    return;
  }
  queue(slot, { article_id, type: was ? 'unsave' : 'save' });
  useFeedback.getState().showToast(was ? 'Removed from saved' : 'Saved, offline too', () => {
    useFeedback.setState((s) => ({ saved: { ...s.saved, [article_id]: was } }));
    cancel(slot);
  });
}

const CAL_COPY = {
  needed: 'Thanks. This helps MAPNAI decide what’s must-know.',
  not_needed: 'Noted. This helps tune must-know.',
  missed: 'Thanks. MAPNAI uses this to catch stories like it sooner.',
} as const;

export function calibrate(article_id: string, kind: 'needed' | 'not_needed' | 'missed') {
  const slot = `${article_id}:calibration`;
  const prev = useFeedback.getState().calibration[article_id];
  useFeedback.setState((s) => ({ calibration: { ...s.calibration, [article_id]: kind } }));
  queue(slot, { article_id, type: kind });
  useFeedback.getState().showToast(CAL_COPY[kind], () => {
    useFeedback.setState((s) => ({ calibration: { ...s.calibration, [article_id]: prev } }));
    cancel(slot);
  });
}

// open / dwell: no undo, once per story per day
export function implicit(article_id: string, type: 'open' | 'dwell', value?: number) {
  const uid = useSession.getState().userId;
  const key = `${uid}|${article_id}|${type}|${isoDate()}`;
  if (useFeedback.getState().sent[key]) return;
  if (type === 'dwell' && (value ?? 0) <= 15) return;
  useFeedback.setState((s) => ({ sent: { ...s.sent, [key]: true } }));
  void send({ article_id, type, value: type === 'dwell' ? Math.min(value ?? 0, 600) : undefined, due: 0 });
}

export function hideToday(key: string) {
  const day = isoDate();
  useFeedback.setState((s) => {
    const keys = s.hiddenToday.day === day ? s.hiddenToday.keys : [];
    return { hiddenToday: { day, keys: [...keys, key] } };
  });
  useFeedback.getState().showToast('Hidden for today', () =>
    useFeedback.setState((s) => ({ hiddenToday: { day, keys: s.hiddenToday.keys.filter((k) => k !== key) } })),
  );
}
