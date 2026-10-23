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
  | 'just_in'
  | 'recap';
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
  kind: 'direct' | 'connected' | 'similar' | 'topic' | 'explore' | 'big_today' | 'alert' | 'recap';
  seed_name?: string;
  seed_weight?: WeightLevel;
  role?: Role;
  via_name?: string;
  relation?: string;
  closest_title?: string;
  topic?: string;
  also?: string[];
};

// Images come from ingestion (og:image / JSON-LD / feed media), referenced at the publisher's URL; when the
// publisher has none, a free Wikipedia image of the story's main entity (source 'wikipedia', with its credit)
export type ArticleImage = {
  url: string; width?: number | null; height?: number | null; alt?: string | null; source?: string;
  credit?: string | null; credit_url?: string | null;
};
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

// Recaps (GET /v1/recaps/daily|weekly): the same stories for every reader in a time zone, frozen once built.
// Daily = the day before (ready 07:00); weekly = Monday to Sunday 22:00. `marks` are this reader's own.
export type RecapKind = 'daily' | 'weekly';
export type RecapMarks = { follows: string | null; in_your_topics: boolean; seen: boolean };
export type RecapItem = StoryItem & {
  rank: number;
  group: string; // daily: 'day'; weekly: 'top' (Stories of the week) or the YYYY-MM-DD the story broke
  story_id: string;
  member_ids: string[];
  happened_at: string;
  span_days?: number | null;
  date_source?: 'published' | 'page_meta' | 'sibling' | 'ingested';
  marks?: RecapMarks;
};
export type RecapSection = { key: string; title: string; count: number };
export type Recap = {
  kind: RecapKind;
  period: string; // daily YYYY-MM-DD, weekly YYYY-Www
  tz: string;
  title: string; // "Wednesday, 21 October" / "19–25 October"
  start: string;
  end: string;
  ready_at: string;
  generated_at: string;
  next_at: string;
  version: number;
  latest: boolean;
  overview: { text: string | null; reason?: string | null } | null;
  items: RecapItem[];
  sections: RecapSection[];
  coverage: {
    articles: number;
    by_domain: Record<string, number>;
    stories: number;
    eligible: number;
    limited: boolean;
    carried_over: number;
  };
};

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

// Insights (GET /v1/users/{id}/insights): developing stories with an AI analysis that is the same for every reader
// (cached per story, made again when the story gains articles) plus this reader's part (`for_you`, `watch`).
// Every claim's `sources` are article ids. Scenarios are analysis, labelled by likelihood only, never a percentage.
export type Likelihood = 'likely' | 'possible' | 'unlikely';
export type InsightClaim = { text: string; sources: string[] };
export type InsightScenario = {
  title: string;
  explanation: string;
  likelihood: Likelihood;
  watch_for: string[];
  sources: string[];
};
export type InsightSource = {
  article_id: string;
  source_name?: string | null;
  title: string;
  url?: string | null;
  published_at?: string | null;
};
export type Insight = {
  story_id: string;
  lead_article_id: string;
  rank: number;
  topic: EngineTopic;
  title: string;
  image_url?: string | null;
  first_seen?: string | null;
  last_updated?: string | null;
  span_days: number;
  source_count: number;
  article_count: number;
  what_happened: InsightClaim;
  why_it_matters: InsightClaim[];
  for_you: { kind: 'direct' | 'connected'; text: string; entities: string[] } | null;
  scenarios: InsightScenario[];
  watch_next: (InsightClaim & { when?: string | null })[];
  // Practical steps for readers the story affects; origin 'risk_agent' = Agent 4's recommendation (no AI analysis)
  actions: (InsightClaim & { origin: 'analysis' | 'risk_agent' })[];
  entities: { key: string; name: string; followed: boolean }[];
  sources: InsightSource[];
  // ok: full analysis; partial: facts held up, scenarios didn't (none shown); fallback: no AI analysis (Groq down)
  analysis: { status: 'ok' | 'partial' | 'fallback'; reason?: string | null; model?: string | null; generated_at?: string | null; version: number; dropped: number };
  watch: { watching: boolean; since?: string | null; new_sources: number; changed: boolean };
  disclaimer: string;
};
export type FollowChange = {
  key: string;
  name: string;
  role?: Role | null;
  weight?: WeightLevel | null;
  this_week: number;
  last_week: number;
  top_story: { article_id: string; title: string; topic?: EngineTopic } | null;
  insight_story_id?: string | null;
};
export type Insights = {
  user_id: string;
  generated_at: string;
  window_h: number;
  personalized: boolean;
  persona_version?: number | null;
  insights: Insight[];
  follows: FollowChange[];
};
