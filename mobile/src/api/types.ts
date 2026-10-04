// API shapes. Built = present in the backend; Proposed = spec §28 contract, served by mocks until built.
// Field names follow PERSONALIZATION_PLAN.md v2; verify against the local build as endpoints land.

export type EngineTopic = 'sports' | 'entertainment_movies' | 'other' | string;
export type Role = 'follows' | 'covers' | 'owns' | 'operates_in' | 'depends_on' | 'regulated_by';
export type WeightLevel = 1 | 2 | 3; // 1 Interested, 2 Important, 3 Essential
export type Section =
  | 'must_know'
  | 'more_you_need'
  | 'interest'
  | 'explore'
  | 'big_today'
  | 'feed'
  | 'just_in';
export type RiskLevel = 'MONITOR' | 'ALERT' | 'ESCALATE' | null;

// ── Built ────────────────────────────────────────────────

export type EntityHit = { key: string; name: string; types: string[]; mention_count: number };

export type Exposure = {
  key: string;
  name: string;
  types?: string[];
  role: Role;
  weight: WeightLevel;
  weight_label: 'low' | 'medium' | 'high';
  provenance: string;
  valid_from?: string;
};

export type Style = { tone: 'plain' | 'analyst'; length: 'short' | 'medium'; jargon: 'low' | 'high' };

export type AlertPrefs = { max_per_day: number; quiet_start: string; quiet_end: string; tz: string };

export type Profile = {
  user_id: string;
  name: string;
  sentences: string[];
  exposures: Exposure[];
  topics: Record<string, number>;
  topic_shares?: Record<string, number>;
  style: Style;
  alert_prefs: AlertPrefs | null;
  beta: Record<string, [number, number]>;
  pi_topk?: { entity: string; score: number; name?: string; path?: unknown }[];
  recent_reads?: { article_id: string; title?: string; t?: string }[];
  persona_version: number;
  created_at?: string;
};

export type Headline = {
  article_id: string;
  title: string;
  topic: EngineTopic;
  source: string;
  url?: string;
  published_at?: string;
  cluster_id?: string;
  entities?: { key: string; name: string }[]; // Proposed addition (spec O3)
};

export type Health = {
  ok: boolean;
  mongo?: { ok: boolean };
  neo4j?: { ok: boolean } | boolean;
  faiss?: { ok: boolean };
  recent_articles?: number;
};

// ── Shared item shape (digest, feed, Big today, search) ───

export type ExplanationParts = {
  kind: 'direct' | 'connected' | 'similar' | 'topic' | 'explore' | 'big_today' | 'alert';
  seed_name?: string;
  seed_weight?: WeightLevel;
  role?: Role;
  via_name?: string;
  relation?: string;
  closest_title?: string;
  topic?: string;
  also?: string[];
};

// Images come from ingestion (og:image / JSON-LD / feed media), referenced at the publisher's URL
export type ArticleImage = { url: string; width?: number | null; height?: number | null; alt?: string | null; source?: string };
export type ArticleMedia = { primary_image: ArticleImage | null; additional_images: ArticleImage[] };

// Counts from the feedback log and comments, leaving the viewer out; `viewer` is their own reaction / save
export type Engagement = { likes: number; dislikes: number; comments: number; saves: number; shares: number };
export type ViewerState = { reaction: 'more' | 'less' | null; saved: boolean };

export type StoryItem = {
  article_id: string;
  url: string;
  title: string;
  summary_short?: string | null;
  summary_long?: string | null;
  media?: ArticleMedia | null;
  author?: string | null;
  engagement?: Engagement;
  viewer?: ViewerState;
  summary_text?: string | null; // Proposed: rendered in the user's style
  body_snippet?: string | null;
  source_name?: string | null;
  published_at?: string | null;
  topic: EngineTopic;
  topic_tags?: string[];
  entities?: { key: string; name: string }[];
  cluster_id?: string;
  cluster_size?: number;
  first_report?: boolean;
  risk_level?: RiskLevel;
  unscored?: boolean;
  urgency_flag?: boolean;
  section?: Section;
  slot?: number;
  explanation?: string;
  explanation_parts?: ExplanationParts;
  another_angle?: { url: string; source_name?: string } | null;
};

export type Digest = {
  user_id: string;
  digest_id?: string;
  generated_at: string;
  items: StoryItem[];
  more_you_need: StoryItem[];
  stale?: boolean;
  policy_version?: string;
};

export type FeedPage = { items: StoryItem[]; next_cursor: string | null; exhausted: boolean; window_h: number };

export type StoryDetail = StoryItem & {
  risk?: {
    score: number;
    level: RiskLevel;
    reasoning?: { severity: number; prominence: number; urgency: number; base_weight: number };
    action_recommendation?: string;
  } | null;
  coverage_words?: string;
  personal?: { explanation?: string; also?: string[]; parts?: ExplanationParts } | null;
  related?: StoryItem[];
};

export type FeedbackType =
  | 'more' | 'less' | 'unreact' | 'save' | 'unsave' | 'share' | 'open' | 'dwell' | 'needed' | 'not_needed' | 'missed';

export type Comment = {
  comment_id: string;
  article_id: string;
  user_id: string;
  author_name: string | null;
  text: string;
  created_at: string;
};

export type Alert = {
  alert_id: string;
  article_id: string;
  cluster_id?: string;
  explanation: string;
  created_at: string;
  deliver_after?: string;
  // Proposed hydration
  title?: string;
  source_name?: string;
  entity_name?: string;
  tier?: 'major' | 'high';
  cluster_size?: number;
};

export type Proposal = {
  proposal_id: string;
  entity_key: string;
  entity_name: string;
  reason: string;
  evidence: { article_id: string; title: string }[];
  role: Role;
  weight: WeightLevel;
};

export type AskSource = {
  article_id: string;
  title: string;
  domain?: string;
  source_name?: string;
  published_at?: string;
  relevance_score?: number;
};

export type AskAnswer = {
  query: string;
  answer: string | null;
  sources: AskSource[];
  confidence: number;
};

export type SearchPage = { items: (StoryItem & { matched_terms?: string[]; connection?: { entity: string; role: Role } })[]; next_cursor: string | null };
