// One function per capability. Engine calls hit the API in hybrid and live; account (auth) calls hit it only in
// live, so hybrid runs the real engine with the demo sign-in (code 123456).
// Mock mode serves everything from mockServer. Screens import from here, never from client/mockServer directly.
import { API_MODE, http } from './client';
import { mock } from './mockServer';
import type {
  Alert, AlertPrefs, AskAnswer, Digest, EntityHit, Exposure, FeedbackType, FeedPage, Headline, Health,
  Profile, Proposal, Role, SearchPage, StoryDetail, StoryItem, Style, WeightLevel,
} from './types';

const built = API_MODE !== 'mock';
const liveAuth = API_MODE === 'live';

// The engine's proposal row → the app's Proposal
const toProposal = (p: any): Proposal => ({
  proposal_id: p.proposal_id,
  entity_key: p.entity_key,
  entity_name: p.name ?? p.entity_key,
  reason: p.why ?? '',
  evidence: p.evidence_articles ?? [],
  role: p.suggested_role,
  weight: p.suggested_weight,
});

const enc = encodeURIComponent;

export const api = {
  // ── Engine: hybrid + live ──────────────────────────────
  health: (): Promise<Health> => (built ? http('/v1/personalization/health') : mock.health()),

  searchEntities: (q: string): Promise<EntityHit[]> =>
    built ? http('/v1/entities/search', { query: { q } }) : mock.searchEntities(q),

  createUser: (name: string): Promise<{ user_id: string; persona_version: number }> =>
    built ? http('/v1/users', { method: 'POST', body: { name } }) : mock.createUser(name),

  headlines: (): Promise<Headline[]> =>
    built
      ? http<any[]>('/v1/onboarding/headlines').then((rows) =>
          rows.map((r) => ({ ...r, source: r.source ?? r.source_name ?? '' })),
        )
      : mock.headlines(),

  onboarding: (id: string, likes: string[], dislikes: string[]) =>
    built
      ? http(`/v1/users/${enc(id)}/onboarding`, { method: 'POST', body: { likes, dislikes } })
      : mock.onboarding(id, likes, dislikes),

  profile: (id: string): Promise<Profile> => (built ? http(`/v1/users/${enc(id)}/profile`) : mock.profile(id)),

  patchExposures: (
    id: string,
    upsert: { key: string; role: Role; weight: WeightLevel }[],
    remove: string[] = [],
  ): Promise<{ exposures: Exposure[]; persona_version: number }> =>
    built
      ? http(`/v1/users/${enc(id)}/exposures`, { method: 'PATCH', body: { upsert, remove } })
      : mock.patchExposures(id, upsert, remove),

  patchTopics: (id: string, topics: Record<string, number | null>) =>
    built
      ? http(`/v1/users/${enc(id)}/topics`, { method: 'PATCH', body: { topics } })
      : mock.patchTopics(id, topics),

  patchStyle: (id: string, style: Partial<Style>) =>
    built ? http(`/v1/users/${enc(id)}/style`, { method: 'PATCH', body: style }) : mock.patchStyle(id, style),

  patchAlertPrefs: (id: string, prefs: Partial<AlertPrefs>) =>
    built
      ? http(`/v1/users/${enc(id)}/alert_prefs`, { method: 'PATCH', body: prefs })
      : mock.patchAlertPrefs(id, prefs),

  digest: (id: string, refresh = false): Promise<Digest> =>
    built ? http(`/v1/users/${enc(id)}/digest`, { query: { refresh } }) : mock.digest(id),

  feedback: (id: string, article_id: string, type: FeedbackType, value?: number, extra?: Record<string, string>) =>
    built
      ? http('/v1/feedback', { method: 'POST', body: { user_id: id, article_id, type, value, ...extra } })
      : mock.feedback(id, article_id, type, value),

  alerts: (id: string, since?: string): Promise<Alert[]> =>
    built ? http(`/v1/users/${enc(id)}/alerts`, { query: { since } }) : mock.alerts(id),

  proposals: (id: string): Promise<Proposal[]> =>
    built
      ? http<any[]>(`/v1/users/${enc(id)}/proposals`, { query: { status: 'pending' } }).then((rows) => rows.map(toProposal))
      : mock.proposals(id),

  decideProposal: (id: string, pid: string, accept: boolean) =>
    built
      ? http(`/v1/users/${enc(id)}/proposals/${enc(pid)}/${accept ? 'accept' : 'reject'}`, { method: 'POST' })
      : mock.decideProposal(id, pid, accept),

  feed: (id: string, cursor: string | null, exclude: string[]): Promise<FeedPage> =>
    built
      ? http(`/v1/users/${enc(id)}/feed`, { query: { cursor: cursor ?? undefined, limit: 10, exclude: exclude.join(',') } })
      : mock.feed(id, cursor, exclude),

  top: (hours = 24, limit = 8): Promise<StoryItem[]> =>
    built ? http('/v1/articles/top', { query: { hours, limit } }) : mock.top(hours, limit),

  story: (article_id: string, userId?: string | null): Promise<StoryDetail> =>
    built
      ? http(`/v1/articles/${enc(article_id)}`, { query: { user_id: userId ?? undefined } })
      : mock.story(article_id, userId),

  cluster: (article_id: string) =>
    built ? http<any[]>(`/v1/clusters/by-article/${enc(article_id)}`) : mock.cluster(article_id),

  saved: (id: string): Promise<StoryItem[]> => (built ? http(`/v1/users/${enc(id)}/saved`) : mock.saved(id)),

  search: (q: string, topic?: string): Promise<SearchPage> =>
    built ? http('/v1/search', { query: { q, topic } }) : mock.search(q, topic),

  ask: (query: string, domain?: string, context_article_id?: string): Promise<AskAnswer> =>
    built
      ? http('/v1/ask', { method: 'POST', body: { query, domain, context_article_id }, timeoutMs: 20000 })
      : mock.ask(query, domain),

  // ── Accounts: live only. Mock accepts code 123456. ──
  register: (email: string, password: string, birthYear: number) =>
    liveAuth
      ? http('/v1/auth/register', { method: 'POST', body: { email, password, birth_year: birthYear } })
      : mock.register(email, password, birthYear),
  verify: (email: string, code: string): Promise<{ access_token: string; refresh_token: string; user_id: string | null }> =>
    liveAuth ? http('/v1/auth/verify', { method: 'POST', body: { email, code } }) : mock.verify(email, code),
  login: (email: string, password: string): Promise<{ access_token: string; refresh_token: string; user_id: string | null }> =>
    liveAuth ? http('/v1/auth/login', { method: 'POST', body: { email, password } }) : mock.login(email, password),
  resend: (email: string) => (liveAuth ? http('/v1/auth/resend', { method: 'POST', body: { email } }) : mock.resend(email)),
  requestReset: (email: string) =>
    liveAuth ? http('/v1/auth/reset/request', { method: 'POST', body: { email } }) : mock.requestReset(email),
  confirmReset: (email: string, code: string, password: string) =>
    liveAuth
      ? http('/v1/auth/reset/confirm', { method: 'POST', body: { email, code, password } })
      : mock.confirmReset(email, code, password),
  // live: the account comes from the Bearer token (the session's access token)
  linkUser: (email: string, user_id: string) =>
    liveAuth ? http('/v1/auth/link', { method: 'POST', body: { user_id } }).then(() => {}) : mock.linkUser(email, user_id),
};
