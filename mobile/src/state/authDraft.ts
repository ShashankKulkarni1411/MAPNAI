// A2 values held in memory until A3 submits (never persisted: it contains the password).
import { create } from 'zustand';

export const useAuthDraft = create<{ email: string; password: string; set: (p: { email?: string; password?: string }) => void }>()((set) => ({
  email: '',
  password: '',
  set: (p) => set(p),
}));

// A7: the date entry is disabled on this device for 24 hours after an under-18 answer
export const ELIGIBILITY_LOCK_KEY = 'mapnai.ageLockUntil';

const COMMON = new Set(['password', 'password1', '12345678', '123456789', 'qwerty123', 'iloveyou', '11111111', 'abc12345', 'football', 'cricket123']);

export function passwordProblem(pw: string): string | null {
  if (pw.length < 8) return 'Use at least 8 characters.';
  if (COMMON.has(pw.toLowerCase())) return 'That password is too common. Try another.';
  return null;
}

export function passwordStrength(pw: string): 'Weak' | 'OK' | 'Strong' {
  let s = 0;
  if (pw.length >= 12) s++;
  if (/[A-Z]/.test(pw) && /[a-z]/.test(pw)) s++;
  if (/\d/.test(pw)) s++;
  if (/[^A-Za-z0-9]/.test(pw)) s++;
  return s >= 3 ? 'Strong' : s >= 1 && pw.length >= 8 ? 'OK' : 'Weak';
}

export const isEmail = (e: string) => /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(e.trim());
