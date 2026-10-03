// On-device stand-in for the backend (EXPO_PUBLIC_API_MODE=mock, and for not-yet-built endpoints in hybrid).
// It follows the engine's rules closely enough to exercise the UI: need = m × seed, τ = 0.2, must-know top 5,
// overflow to more_you_need, at most 3 per topic in For you, one explore slot. It is not the ranking engine.
import AsyncStorage from '@react-native-async-storage/async-storage';

import { ApiError } from './client';
import { ARTICLES, COMENTIONS, ENTITIES, FixtureArticle } from './fixtures';
import type {
  Alert, AlertPrefs, AskAnswer, Digest, EntityHit, Exposure, FeedbackType, FeedPage, Headline, Health,
  Profile, Proposal, Role, SearchPage, Section, StoryDetail, StoryItem, Style, WeightLevel,
} from './types';

const TAU = 0.2;
const DB_KEY = 'mapnai.mockdb';

type MockUser = {
  user_id: string;
  name: string;
  topics: Record<string, number>;
  style: Style;
  alert_prefs: AlertPrefs;
  exposures: Exposure[];
  beta: Record<string, [number, number]>;
  history: { article_id: string; title: string; t: string; w: number }[];
  saved: string[];
  rejected: string[];
  persona_version: number;
  created_at: string;
};
type Account = { email: string; password: string; birthYear: number; verified: boolean; user_id?: string };
type DB = { users: Record<string, MockUser>; accounts: Record<string, Account> };

let db: DB | null = null;

async function load(): Promise<DB> {
  if (db) return db;
  try {
    const raw = await AsyncStorage.getItem(DB_KEY);
    db = raw ? JSON.parse(raw) : null;
  } catch {}
  db = db ?? { users: {}, accounts: {} };
  return db!;
}
async function save() {
  try {
    await AsyncStorage.setItem(DB_KEY, JSON.stringify(db));
  } catch {}
}
const delay = (ms = 250) => new Promise((r) => setTimeout(r, ms));
const uuid = () => 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
  const r = (Math.random() * 16) | 0;
  return (c === 'x' ? r : (r & 0x3) | 0x8).toString(16);
});
const nowIso = () => new Date().toISOString();
const ago = (h: number) => new Date(Date.now() - h * 3_600_000).toISOString();
const prior = (w: number): [number, number] => [1 + 3 * w, 1 + 3 * (1 - w)];
const theta = (b?: [number, number]) => (b ? b[0] / (b[0] + b[1]) : 0.5);
const LABEL = { 1: 'low', 2: 'medium', 3: 'high' } as const;

async function user(id: string): Promise<MockUser> {
  const d = await load();
  const u = d.users[id];
  if (!u) throw new ApiError(404, `user ${id} not found`);
  return u;
}
function bump(u: MockUser) {
  u.persona_version += 1;
  void save();
}

// ── Scoring ──────────────────────────────────────────────

function seeds(u: MockUser): Map<string, { score: number; via?: string; seed: Exposure }> {
  const pi = new Map<string, { score: number; via?: string; seed: Exposure }>();
  for (const e of u.exposures) {
    const s = e.weight / 3;
    if ((pi.get(e.key)?.score ?? 0) < s) pi.set(e.key, { score: s, seed: e });
  }
  for (const e of u.exposures) {
    for (const n of COMENTIONS[e.key] ?? []) {
      const s = Math.min(0.1, 0.1 * (e.weight / 3));
      if (!pi.has(n) || pi.get(n)!.score < s) pi.set(n, { score: s, via: n, seed: e });
    }
  }
  return pi;
}

function need(a: FixtureArticle, pi: ReturnType<typeof seeds>) {
  let best = 0;
  let hit: { score: number; via?: string; seed: Exposure } | undefined;
  for (const k of a.entities) {
    const p = pi.get(k);
    if (p && p.score > best) {
      best = p.score;
      hit = p;
    }
  }
  return { need: a.m * best, hit };
}

function toItem(a: FixtureArticle, section?: Section, slot?: number, extra?: Partial<StoryItem>): StoryItem {
  return {
    article_id: a.id,
    url: `https://example.com/${a.id}`,
    title: a.title,
    summary_short: a.summary,
    body_snippet: a.body ?? null,
    source_name: a.source,
    published_at: ago(a.ageH),
    topic: a.topic,
    topic_tags: a.topicTag ? [a.topicTag] : [],
    entities: a.entities.slice(0, 3).map((k) => ({ key: k, name: ENTITIES[k]?.name ?? k })),
    cluster_id: `c-${a.id}`,
    cluster_size: a.sources,
    first_report: a.first,
    risk_level: a.unscored ? null : a.risk,
    unscored: a.unscored,
    urgency_flag: !!a.urgent,
    section,
    slot,
    another_angle: a.angle ? { url: `https://example.com/${a.id}/angle`, source_name: a.angle } : null,
    ...extra,
  };
}

function explain(a: FixtureArticle, u: MockUser, pi: ReturnType<typeof seeds>, section: Section): Partial<StoryItem> {
  const { hit } = need(a, pi);
  const also = a.entities
    .filter((k) => u.exposures.some((e) => e.key === k) && k !== hit?.seed.key)
    .map((k) => ENTITIES[k]?.name ?? k);
  if (hit && !hit.via) {
    const verb = { follows: 'follow', covers: 'cover', owns: 'have a stake in', operates_in: 'work in', depends_on: 'depend on', regulated_by: 'are governed by' }[hit.seed.role];
    return {
      explanation: `You ${verb} ${hit.seed.name}, which this story covers.`,
      explanation_parts: { kind: 'direct', seed_name: hit.seed.name, seed_weight: hit.seed.weight, role: hit.seed.role, also },
    };
  }
  if (hit?.via) {
    const via = ENTITIES[hit.via]?.name ?? hit.via;
    return {
      explanation: `You follow ${hit.seed.name}; this story is about ${via} (often mentioned with ${hit.seed.name}).`,
      explanation_parts: { kind: 'connected', seed_name: hit.seed.name, seed_weight: hit.seed.weight, role: hit.seed.role, via_name: via, relation: 'often mentioned with' },
    };
  }
  if (section === 'explore') {
    const t = a.topicTag ?? (a.topic === 'sports' ? 'Sports' : a.topic === 'entertainment_movies' ? 'Film' : 'General');
    return { explanation: `Something new for you: ${t}`, explanation_parts: { kind: 'explore', topic: t } };
  }
  const read = u.history.find((h) => {
    const r = ARTICLES.find((x) => x.id === h.article_id);
    return r && r.id !== a.id && r.entities.some((k) => a.entities.includes(k));
  });
  if (read) return { explanation: `Similar to '${read.title}'`, explanation_parts: { kind: 'similar', closest_title: read.title } };
  const t = a.topic === 'sports' ? 'Sports' : a.topic === 'entertainment_movies' ? 'Film' : 'General';
  return { explanation: `Because you like ${t}`, explanation_parts: { kind: 'topic', topic: t } };
}

function interestScore(a: FixtureArticle, u: MockUser) {
  const tTopic = theta(u.beta[`topic:${a.topic}`] ?? prior(u.topics[a.topic] ?? 0.3));
  const ents = a.entities.map((k) => theta(u.beta[`entity:${k}`]));
  const tEnt = ents.length ? Math.max(...ents) : 0.5;
  return 0.6 * tTopic + 0.4 * tEnt + 0.05 * (1 - a.ageH / 48);
}

function slate(u: MockUser) {
  const pi = seeds(u);
  const pool = ARTICLES.filter((a) => a.ageH <= 48);
  const needs = pool.map((a) => ({ a, ...need(a, pi) })).filter((x) => x.need >= TAU).sort((x, y) => y.need - x.need);
  const must = needs.slice(0, 5).map((x) => x.a);
  const more = needs.slice(5).map((x) => x.a);
  const taken = new Set([...must, ...more].map((a) => a.id));
  const ranked = pool
    .filter((a) => !taken.has(a.id) && a.topic !== 'other')
    .filter((a) => (u.topics[a.topic] ?? 0.6) > 0.05 || need(a, pi).need > 0)
    .map((a) => ({ a, s: interestScore(a, u) + 0.3 * need(a, pi).need }))
    .sort((x, y) => y.s - x.s);
  const perTopic: Record<string, number> = {};
  const interest: FixtureArticle[] = [];
  for (const { a } of ranked) {
    if (must.length + interest.length >= 9) break;
    if ((perTopic[a.topic] ?? 0) >= 3) continue;
    perTopic[a.topic] = (perTopic[a.topic] ?? 0) + 1;
    interest.push(a);
  }
  const usedTopics = new Set([...must, ...interest].map((a) => a.topic));
  const explore = pool.find((a) => !taken.has(a.id) && !interest.includes(a) && !usedTopics.has(a.topic))
    ?? pool.find((a) => !taken.has(a.id) && !interest.includes(a) && a.topic !== 'sports');
  return { pi, must, more, interest, explore };
}

// ── Built endpoints ──────────────────────────────────────

export const mock = {
  async health(): Promise<Health> {
    await delay(80);
    return { ok: true, recent_articles: ARTICLES.length };
  },

  async searchEntities(q: string): Promise<EntityHit[]> {
    await delay(150);
    const k = q.trim().toLowerCase();
    return Object.entries(ENTITIES)
      .filter(([key, e]) => key.startsWith(k) || key.includes(k) || e.name.toLowerCase().includes(k))
      .sort((a, b) => b[1].mentions - a[1].mentions)
      .slice(0, 10)
      .map(([key, e]) => ({ key, name: e.name, types: [], mention_count: e.mentions }));
  },

  async createUser(name: string): Promise<{ user_id: string; persona_version: number }> {
    const d = await load();
    const user_id = uuid();
    d.users[user_id] = {
      user_id, name, topics: {}, style: { tone: 'plain', length: 'short', jargon: 'low' },
      alert_prefs: { max_per_day: 3, quiet_start: '22:00', quiet_end: '07:00', tz: 'Asia/Kolkata' },
      exposures: [], beta: {}, history: [], saved: [], rejected: [], persona_version: 1, created_at: nowIso(),
    };
    await save();
    return { user_id, persona_version: 1 };
  },

  async headlines(): Promise<Headline[]> {
    await delay();
    const sports = ARTICLES.filter((a) => a.topic === 'sports').sort((a, b) => b.m - a.m);
    const film = ARTICLES.filter((a) => a.topic === 'entertainment_movies').sort((a, b) => b.m - a.m);
    const out: Headline[] = [];
    for (let i = 0; out.length < 10 && (sports[i] || film[i]); i++) {
      for (const a of [sports[i], film[i]]) {
        if (a && out.length < 10)
          out.push({
            article_id: a.id, title: a.title, topic: a.topic, source: a.source, published_at: ago(a.ageH),
            entities: a.entities.slice(0, 3).map((k) => ({ key: k, name: ENTITIES[k]?.name ?? k })),
          });
      }
    }
    return out;
  },

  async onboarding(id: string, likes: string[], dislikes: string[]) {
    const u = await user(id);
    for (const [ids, d] of [[likes, [1, 0]], [dislikes, [0, 1]]] as const) {
      for (const aid of ids) {
        const a = ARTICLES.find((x) => x.id === aid);
        if (!a) continue;
        for (const key of [`topic:${a.topic}`, ...a.entities.slice(0, 3).map((k) => `entity:${k}`)]) {
          const b = u.beta[key] ?? [1, 1];
          u.beta[key] = [b[0] + d[0], b[1] + d[1]];
        }
        if (d[0]) u.history.push({ article_id: a.id, title: a.title, t: nowIso(), w: 1 });
      }
    }
    bump(u);
    return { user_id: id, persona_version: u.persona_version };
  },

  async profile(id: string): Promise<Profile> {
    await delay(120);
    const u = await user(id);
    const sentences = [
      ...u.exposures.map((e) => `You ${e.role === 'follows' ? 'follow' : e.role.replace('_', ' ')} ${e.name} (${e.weight_label}).`),
    ];
    const pi = [...seeds(u).entries()].map(([key, v]) => ({ key, score: v.score, name: ENTITIES[key]?.name ?? key }));
    return {
      user_id: u.user_id, name: u.name, sentences, exposures: u.exposures, topics: u.topics, style: u.style,
      alert_prefs: u.alert_prefs, beta: u.beta, pi_topk: pi, persona_version: u.persona_version,
      recent_reads: [...u.history].reverse().slice(0, 10), created_at: u.created_at,
    };
  },

  async patchExposures(id: string, upsert: { key: string; role: Role; weight: WeightLevel }[], remove: string[]) {
    const u = await user(id);
    for (const e of upsert) {
      if (!ENTITIES[e.key]) throw new ApiError(404, `entity key '${e.key}' not found`);
      u.exposures = u.exposures.filter((x) => x.key !== e.key);
      u.exposures.push({
        key: e.key, name: ENTITIES[e.key].name, role: e.role, weight: e.weight, weight_label: LABEL[e.weight],
        provenance: 'declared', valid_from: nowIso(),
      });
      u.beta[`entity:${e.key}`] = u.beta[`entity:${e.key}`] ?? prior(e.weight / 3);
    }
    u.exposures = u.exposures.filter((x) => !remove.includes(x.key));
    bump(u);
    return { user_id: id, exposures: u.exposures, persona_version: u.persona_version };
  },

  async patchTopics(id: string, topics: Record<string, number | null>) {
    const u = await user(id);
    for (const [t, w] of Object.entries(topics)) {
      if (w === null) delete u.topics[t];
      else {
        u.topics[t] = w;
        u.beta[`topic:${t}`] = prior(w); // explicit change resets to the new prior (open decision #6)
      }
    }
    bump(u);
    return { user_id: id, topics: u.topics, persona_version: u.persona_version };
  },

  async patchStyle(id: string, style: Partial<Style>) {
    const u = await user(id);
    u.style = { ...u.style, ...style };
    bump(u);
    return { user_id: id, style: u.style, persona_version: u.persona_version };
  },

  async patchAlertPrefs(id: string, prefs: Partial<AlertPrefs>) {
    const u = await user(id);
    u.alert_prefs = { ...u.alert_prefs, ...prefs };
    bump(u);
    return { user_id: id, alert_prefs: u.alert_prefs, persona_version: u.persona_version };
  },

  async digest(id: string): Promise<Digest> {
    await delay(400);
    const u = await user(id);
    const { pi, must, more, interest, explore } = slate(u);
    const items: StoryItem[] = [
      ...must.map((a, i) => toItem(a, 'must_know', i, explain(a, u, pi, 'must_know'))),
      ...interest.map((a, i) => toItem(a, 'interest', must.length + i, explain(a, u, pi, 'interest'))),
      ...(explore ? [toItem(explore, 'explore', 9, explain(explore, u, pi, 'explore'))] : []),
    ];
    return {
      user_id: id, digest_id: `d-${Date.now()}`, generated_at: nowIso(), items,
      more_you_need: more.map((a, i) => toItem(a, 'more_you_need', i, explain(a, u, pi, 'more_you_need'))),
      policy_version: 'mock',
    };
  },

  async feedback(id: string, article_id: string, type: FeedbackType, value?: number) {
    const u = await user(id);
    const a = ARTICLES.find((x) => x.id === article_id);
    if (!a) return { ok: true };
    const d: Partial<Record<FeedbackType, [number, number]>> = { more: [1, 0], less: [0, 1], open: [0.5, 0], dwell: [0.5, 0] };
    const delta = d[type];
    if (delta && !(type === 'dwell' && (value ?? 0) < 15)) {
      for (const key of [`topic:${a.topic}`, ...a.entities.slice(0, 3).map((k) => `entity:${k}`)]) {
        const b = u.beta[key] ?? [1, 1];
        u.beta[key] = [b[0] + delta[0], b[1] + delta[1]];
      }
    }
    if (type === 'save' && !u.saved.includes(a.id)) u.saved.unshift(a.id);
    if (type === 'unsave') u.saved = u.saved.filter((x) => x !== a.id);
    if (['more', 'open', 'dwell', 'save'].includes(type) && !u.history.some((h) => h.article_id === a.id))
      u.history.push({ article_id: a.id, title: a.title, t: nowIso(), w: type === 'more' || type === 'save' ? 2 : 1 });
    void save();
    return { ok: true };
  },

  // ── Proposed endpoints ─────────────────────────────────

  async feed(id: string, cursor: string | null, exclude: string[]): Promise<FeedPage> {
    await delay(300);
    const u = await user(id);
    const pi = seeds(u);
    const page = Number(cursor ?? 0);
    const rest = ARTICLES.filter((a) => !exclude.includes(a.id))
      .map((a) => ({ a, s: interestScore(a, u) + 0.3 * need(a, pi).need }))
      .sort((x, y) => y.s - x.s)
      .slice(page * 10, page * 10 + 10);
    return {
      items: rest.map(({ a }, i) => toItem(a, 'feed', i, explain(a, u, pi, 'feed'))),
      next_cursor: rest.length === 10 ? String(page + 1) : null,
      exhausted: rest.length < 10,
      window_h: 48,
    };
  },

  async top(hours = 24, limit = 8): Promise<StoryItem[]> {
    await delay(200);
    return ARTICLES.filter((a) => a.ageH <= hours)
      .sort((a, b) => b.m - a.m)
      .slice(0, limit)
      .map((a) => toItem(a, 'big_today', undefined, {
        explanation: `Covered by ${a.sources} sources today`,
        explanation_parts: { kind: 'big_today' },
      }));
  },

  async story(article_id: string, userId?: string | null): Promise<StoryDetail> {
    await delay(250);
    const a = ARTICLES.find((x) => x.id === article_id);
    if (!a) throw new ApiError(404, 'article not found');
    let personal: StoryDetail['personal'] = null;
    if (userId) {
      const u = await user(userId);
      const pi = seeds(u);
      const ex = explain(a, u, pi, 'interest');
      if (ex.explanation_parts?.kind === 'direct' || ex.explanation_parts?.kind === 'connected')
        personal = { explanation: ex.explanation, parts: ex.explanation_parts, also: ex.explanation_parts.also };
    }
    const related = ARTICLES.filter((x) => x.id !== a.id && x.entities.some((k) => a.entities.includes(k)))
      .slice(0, 5)
      .map((x) => toItem(x));
    return {
      ...toItem(a),
      summary_long: a.summaryLong ?? a.summary,
      risk: a.unscored || !a.factors
        ? null
        : {
            score: Math.round(a.m * 100), level: a.risk,
            reasoning: { severity: a.factors[0], prominence: a.factors[1], urgency: a.factors[2], base_weight: a.factors[3] },
            action_recommendation: a.action,
          },
      personal,
      related,
    };
  },

  async cluster(article_id: string) {
    await delay(200);
    const a = ARTICLES.find((x) => x.id === article_id);
    if (!a) throw new ApiError(404, 'article not found');
    const outlets = [a.source, a.angle ?? 'Reuters', 'The Hindu', 'NDTV', 'Hindustan Times', 'Indian Express', 'Mint', 'Scroll', 'The Print', 'Firstpost', 'News18', 'India Today', 'Deccan Herald', 'WION'];
    return outlets.slice(0, a.sources).map((s, i) => ({
      article_id: `${a.id}-${i}`, source_name: s, title: i === 0 ? a.title : `${a.title.split(' ').slice(0, 6).join(' ')}…`,
      published_at: ago(a.ageH + i * 0.5), first_report: i === 0 && a.first, url: `https://example.com/${a.id}/${i}`,
    }));
  },

  async alerts(id: string): Promise<Alert[]> {
    await delay(150);
    const u = await user(id);
    const pi = seeds(u);
    return ARTICLES.map((a) => ({ a, ...need(a, pi) }))
      .filter((x) => x.need >= 0.5 && x.a.m >= 0.6 && x.hit && !x.hit.via)
      .slice(0, u.alert_prefs.max_per_day)
      .map(({ a, hit }) => ({
        alert_id: `al-${a.id}`, article_id: a.id, cluster_id: `c-${a.id}`, created_at: ago(a.ageH),
        explanation: `You follow ${hit!.seed.name} (${hit!.seed.weight === 3 ? 'Essential' : 'Important'}).`,
        title: a.title, source_name: a.source, entity_name: hit!.seed.name,
        tier: a.risk === 'ESCALATE' || a.m >= 0.8 ? 'major' : 'high', cluster_size: a.sources,
      }));
  },

  async proposals(id: string): Promise<Proposal[]> {
    await delay(150);
    const u = await user(id);
    const cands = Object.entries(u.beta)
      .filter(([k, b]) => k.startsWith('entity:') && theta(b) >= 0.7 && b[0] >= 3)
      .map(([k]) => k.slice(7))
      .filter((k) => !u.exposures.some((e) => e.key === k) && !u.rejected.includes(k) && ENTITIES[k]);
    return cands.slice(0, 2).map((k) => ({
      proposal_id: `p-${k}`, entity_key: k, entity_name: ENTITIES[k].name,
      reason: `You've read several stories about ${ENTITIES[k].name} this week.`,
      evidence: ARTICLES.filter((a) => a.entities.includes(k)).slice(0, 3).map((a) => ({ article_id: a.id, title: a.title })),
      role: 'follows', weight: 1,
    }));
  },

  async decideProposal(id: string, pid: string, accept: boolean) {
    const u = await user(id);
    const key = pid.replace(/^p-/, '');
    if (accept) await mock.patchExposures(id, [{ key, role: 'follows', weight: 1 }], []);
    else u.rejected.push(key);
    void save();
    return { ok: true };
  },

  async saved(id: string): Promise<StoryItem[]> {
    const u = await user(id);
    return u.saved.map((aid) => ARTICLES.find((a) => a.id === aid)).filter(Boolean).map((a) => toItem(a!));
  },

  async search(q: string, topic?: string): Promise<SearchPage> {
    await delay(250);
    const terms = q.toLowerCase().split(/\s+/).filter((t) => t.length > 1);
    const items = ARTICLES.filter((a) => !topic || a.topic === topic)
      .map((a) => {
        const hay = `${a.title} ${a.summary ?? ''} ${a.entities.map((k) => ENTITIES[k]?.name).join(' ')}`.toLowerCase();
        const matched = terms.filter((t) => hay.includes(t));
        return { a, matched };
      })
      .filter((x) => x.matched.length > 0)
      .sort((x, y) => y.matched.length - x.matched.length || x.a.ageH - y.a.ageH)
      .map(({ a, matched }) => ({ ...toItem(a), matched_terms: matched }));
    return { items, next_cursor: null };
  },

  async ask(query: string, domain?: string): Promise<AskAnswer> {
    await delay(1200);
    const { items } = await mock.search(query.replace(/[?]/g, ''), domain);
    if (!items.length) return { query, answer: null, sources: [], confidence: 0 };
    const top = items.slice(0, 5);
    const answer = top
      .slice(0, 2)
      .map((s, i) => `${s.summary_short ?? s.title} [${i + 1}]`)
      .join(' ');
    return {
      query, answer,
      sources: top.map((s) => ({ article_id: s.article_id, title: s.title, domain: s.topic, source_name: s.source_name ?? '', published_at: s.published_at ?? '' })),
      confidence: Math.min(0.95, 0.35 + 0.15 * (top[0].matched_terms?.length ?? 1)),
    };
  },

  // ── Auth (Proposed) ────────────────────────────────────
  async register(email: string, password: string, birthYear: number) {
    await delay(400);
    const d = await load();
    const k = email.toLowerCase();
    if (d.accounts[k]?.verified) throw new ApiError(409, 'email taken');
    d.accounts[k] = { email: k, password, birthYear, verified: false };
    await save();
    return { ok: true };
  },
  async verify(email: string, code: string) {
    await delay(300);
    const d = await load();
    const acc = d.accounts[email.toLowerCase()];
    if (!acc || code !== '123456') throw new ApiError(422, 'wrong code');
    acc.verified = true;
    await save();
    return { access_token: `mock.${uuid()}`, refresh_token: `mock.${uuid()}`, user_id: acc.user_id ?? null };
  },
  async login(email: string, password: string) {
    await delay(400);
    const d = await load();
    const acc = d.accounts[email.toLowerCase()];
    if (!acc || acc.password !== password) throw new ApiError(401, 'Email or password is incorrect');
    if (!acc.verified) throw new ApiError(403, 'unverified');
    return { access_token: `mock.${uuid()}`, refresh_token: `mock.${uuid()}`, user_id: acc.user_id ?? null };
  },
  async linkUser(email: string, user_id: string) {
    const d = await load();
    const acc = d.accounts[email.toLowerCase()];
    if (acc) acc.user_id = user_id;
    await save();
  },
};
