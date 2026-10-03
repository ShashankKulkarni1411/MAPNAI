// UI words for engine values. Users never see engine terms (spec §2 conventions, §20 wording rules).
import type { EngineTopic, Role, RiskLevel, Section, WeightLevel } from '@/api/types';

export type TopicLabel = 'Sports' | 'Film' | 'General';

export function topicLabel(t: EngineTopic | undefined | null): TopicLabel {
  if (t === 'sports') return 'Sports';
  if (t === 'entertainment_movies') return 'Film';
  return 'General';
}

export const importance: Record<WeightLevel, { label: string; outcome: string }> = {
  3: { label: 'Essential', outcome: 'Big news becomes must-know and can alert you.' },
  2: { label: 'Important', outcome: 'Notable news becomes must-know. Alerts only for major news.' },
  1: { label: 'Interested', outcome: 'Shows in For you. Must-know only for the biggest stories. No alerts.' },
};

// "You {verb} X"
export const roleVerb: Record<Role, string> = {
  follows: 'follow',
  covers: 'cover',
  owns: 'have a stake in',
  operates_in: 'work in',
  depends_on: 'depend on',
  regulated_by: 'are governed by',
};

// Order shown in the connection sheet; fans see only the first unless expanded
export const roleOrder: Role[] = ['follows', 'covers', 'operates_in', 'owns', 'depends_on', 'regulated_by'];

export const roleTitle: Record<Role, string> = {
  follows: 'Follow',
  covers: 'I cover it',
  operates_in: 'I work in it',
  owns: 'I have a stake in it',
  depends_on: 'My work depends on it',
  regulated_by: "I'm governed by it",
};

export const sectionLabel: Record<Section, string> = {
  must_know: 'Must know',
  more_you_need: 'More you may need',
  interest: 'For you',
  explore: 'New for you',
  big_today: 'Big today',
  feed: 'More for you',
  just_in: 'Just in',
};

export const sectionMeaning: Record<Section, string> = {
  must_know: 'Must know: big news about something you follow.',
  more_you_need: 'More you may need: also big news about what you follow.',
  interest: 'For you: picked from what you like to read.',
  explore: 'New for you: MAPNAI tries one new topic a day so your brief doesn’t narrow.',
  big_today: 'Big today: one of today’s most covered stories, shown to everyone.',
  feed: 'More for you: ranked from your latest reading.',
  just_in: 'Just in: big news about something you follow, as it happened.',
};

// High impact for ALERT, Major for ESCALATE, nothing otherwise (and never for unscored)
export function impactBadge(level: RiskLevel | undefined, unscored?: boolean): 'High impact' | 'Major' | null {
  if (unscored) return null;
  if (level === 'ESCALATE') return 'Major';
  if (level === 'ALERT') return 'High impact';
  return null;
}

// Topic weights: A lot = 1.0, Some = 0.6, Not for me = 0.0 (spec O2)
export const topicLevels = [
  { label: 'A lot', value: 1.0 },
  { label: 'Some', value: 0.6 },
  { label: 'Not for me', value: 0.0 },
] as const;

export function topicLevelFor(w: number | undefined): string {
  if (w === undefined) return 'Some';
  if (w >= 0.8) return 'A lot';
  if (w <= 0.1) return 'Not for me';
  return 'Some';
}

// θ → 5-level bar (spec P2)
export function thetaLevel(theta: number): { level: 1 | 2 | 3 | 4 | 5; label: string } {
  if (theta < 0.3) return { level: 1, label: 'Very low' };
  if (theta < 0.45) return { level: 2, label: 'Low' };
  if (theta < 0.6) return { level: 3, label: 'Moderate' };
  if (theta < 0.75) return { level: 4, label: 'Strong' };
  return { level: 5, label: 'Very strong' };
}

export function titleCaseKey(key: string): string {
  return key.replace(/\b\w/g, (m) => m.toUpperCase());
}
