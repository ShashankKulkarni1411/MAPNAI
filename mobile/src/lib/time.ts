import * as Localization from 'expo-localization';

export function parseTs(s?: string | null): Date | null {
  if (!s) return null;
  const d = new Date(s);
  return Number.isNaN(d.getTime()) ? null : d;
}

// "2h", "35m", "3d". Null when the publish time can't be parsed (the age is hidden then).
export function ageLabel(s?: string | null, now = new Date()): string | null {
  const d = parseTs(s);
  if (!d) return null;
  const mins = Math.max(0, Math.round((now.getTime() - d.getTime()) / 60000));
  if (mins < 60) return `${Math.max(1, mins)}m`;
  const h = Math.round(mins / 60);
  if (h < 48) return `${h}h`;
  return `${Math.round(h / 24)}d`;
}

export function hoursSince(s?: string | null, now = new Date()): number {
  const d = parseTs(s);
  return d ? (now.getTime() - d.getTime()) / 3_600_000 : Infinity;
}

export function clockLabel(s?: string | null): string {
  const d = parseTs(s);
  if (!d) return '';
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });
}

export function greeting(now = new Date()): string {
  const h = now.getHours();
  if (h < 12) return 'Good morning';
  if (h < 17) return 'Good afternoon';
  return 'Good evening';
}

export function dayLabel(now = new Date()): string {
  return now.toLocaleDateString([], { weekday: 'short', day: 'numeric', month: 'short' });
}

export function isoDate(now = new Date()): string {
  return now.toISOString().slice(0, 10);
}

// The device's IANA time zone: recaps and "today" are cut at this zone's midnights
export function deviceTz(): string {
  return Localization.getCalendars()[0]?.timeZone ?? Intl.DateTimeFormat().resolvedOptions().timeZone ?? 'Asia/Kolkata';
}

// YYYY-MM-DD of the device's local day, `offset` days from today (−1 = yesterday)
export function localDate(offset = 0, now = new Date()): string {
  const d = new Date(now.getFullYear(), now.getMonth(), now.getDate() + offset);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}
