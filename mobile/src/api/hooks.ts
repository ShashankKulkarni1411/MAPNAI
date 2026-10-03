import AsyncStorage from '@react-native-async-storage/async-storage';
import { QueryClient, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef } from 'react';

import { useSession } from '@/state/session';
import { isoDate } from '@/lib/time';
import { api } from './endpoints';
import type { Digest, Profile, Role, WeightLevel } from './types';

export const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 2, refetchOnWindowFocus: false, staleTime: 60_000 } },
});

const DIGEST_CACHE = 'mapnai.digest';

export function useUserId(): string {
  return useSession((s) => s.userId) ?? '';
}

export function useProfile() {
  const uid = useUserId();
  return useQuery({ queryKey: ['profile', uid], queryFn: () => api.profile(uid), enabled: !!uid });
}

// Home digest. Every digest GET logs impressions server-side, so we keep one per session and refetch only on:
// cold start when the cache isn't today's or is >2 h old, pull-to-refresh (≥60 s apart), or a persona_version bump.
export function useDigest() {
  const uid = useUserId();
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ['digest', uid],
    enabled: !!uid,
    staleTime: 2 * 60 * 60_000,
    queryFn: async () => {
      const d = await api.digest(uid, false);
      void AsyncStorage.setItem(DIGEST_CACHE, JSON.stringify(d)).catch(() => {});
      return d;
    },
  });

  // Cold start: show the device cache instantly, before the network answers
  const seeded = useRef(false);
  useEffect(() => {
    if (seeded.current || !uid) return;
    seeded.current = true;
    AsyncStorage.getItem(DIGEST_CACHE)
      .then((raw) => {
        if (!raw || qc.getQueryData(['digest', uid])) return;
        const d: Digest = JSON.parse(raw);
        if (d.user_id !== uid) return;
        const fresh = d.generated_at.slice(0, 10) === isoDate() && Date.now() - Date.parse(d.generated_at) < 2 * 3600_000;
        qc.setQueryData(['digest', uid], d, { updatedAt: fresh ? Date.now() : 0 });
      })
      .catch(() => {});
  }, [uid, qc]);

  const lastRefresh = useRef(0);
  const refresh = async () => {
    if (Date.now() - lastRefresh.current < 60_000) return;
    lastRefresh.current = Date.now();
    const d = await api.digest(uid, true);
    void AsyncStorage.setItem(DIGEST_CACHE, JSON.stringify(d)).catch(() => {});
    qc.setQueryData(['digest', uid], d);
  };
  return { ...q, refresh };
}

export function useTop(hours = 24) {
  return useQuery({ queryKey: ['top', hours], queryFn: () => api.top(hours, 8), staleTime: 10 * 60_000 });
}

export function useAlerts() {
  const uid = useUserId();
  return useQuery({ queryKey: ['alerts', uid], queryFn: () => api.alerts(uid), enabled: !!uid, staleTime: 5 * 60_000 });
}

export function useProposals() {
  const uid = useUserId();
  return useQuery({ queryKey: ['proposals', uid], queryFn: () => api.proposals(uid), enabled: !!uid });
}

export function useHealth() {
  return useQuery({ queryKey: ['health'], queryFn: api.health, staleTime: 5 * 60_000, refetchInterval: 5 * 60_000, retry: 0 });
}

// Any declared edit bumps persona_version server-side, which invalidates the cached brief and Insights
export function invalidatePersona() {
  void queryClient.invalidateQueries({ queryKey: ['profile'] });
  void queryClient.invalidateQueries({ queryKey: ['digest'] });
  void queryClient.invalidateQueries({ queryKey: ['proposals'] });
  void queryClient.invalidateQueries({ queryKey: ['alerts'] });
  pendingBriefUpdate.flag = true;
}

// Home shows "Your brief was updated" once after an edit
export const pendingBriefUpdate = { flag: false };

export function useFollow() {
  const uid = useUserId();
  return useMutation({
    mutationFn: (v: { upsert?: { key: string; role: Role; weight: WeightLevel }[]; remove?: string[] }) =>
      api.patchExposures(uid, v.upsert ?? [], v.remove ?? []),
    onSuccess: invalidatePersona,
  });
}

export function followOf(profile: Profile | undefined, key: string) {
  return profile?.exposures.find((e) => e.key === key);
}
