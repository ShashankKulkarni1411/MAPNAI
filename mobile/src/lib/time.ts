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
