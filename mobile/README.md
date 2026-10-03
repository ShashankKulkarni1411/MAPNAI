# MAPNAI mobile

React Native + Expo (SDK 57, Expo Router) app for MAPNAI, built from the *Product, UX & Personalization Design Spec*.

## Run

```bash
cd mobile
npm install
cp .env.example .env.local   # pick the API mode, see below
npx expo start               # scan the QR code with Expo Go, or press a / i
```

Demo sign-up: any email and an 8+ character password; the verification code is `123456`.

## API modes (`EXPO_PUBLIC_API_MODE`)

| Mode | What it does |
|---|---|
| `mock` (default) | Everything comes from on-device fixtures in `src/api/mockServer.ts`. No backend needed. |
| `hybrid` | Endpoints the backend has today go to `EXPO_PUBLIC_API_URL`: users, profile, entity search, onboarding headlines and swipes, the four PATCH edits, health. The rest use fixtures. |
| `live` | Every call goes to the API, using the contract in spec §28. |

For `hybrid`, run the backend with `python run_api.py --host 0.0.0.0` and set `EXPO_PUBLIC_API_URL` to your PC's LAN IP.

The mock follows the engine's rules closely enough to exercise the UI: need = materiality × follow strength, τ = 0.2, at most 5 must-knows (the rest go to "More you may need"), at most 3 For you stories per topic, one explore slot, alerts at need ≥ 0.5 and materiality ≥ 0.6. It is not the ranking engine.

## Layout

```
src/app/            routes (Expo Router): (auth) A1–A7, onboarding O1–O6, (tabs) Home/Flash/Insights/Profile,
                    ask (K1/K2), story/[id] (S1), sources/[id] (S2), entity/[key] (S3), search (Q1/Q2),
                    notifications (N1), profile/* (P2–P9), settings/* (T1–T7)
src/api/            types (spec §28 shapes), endpoints (one function per capability), mockServer, hooks
src/components/     design-system pieces, StoryCard, Why/Actions sheets, FollowPicker, SwipeDeck
src/state/          session (secure store), feedback queue with 5 s undo, prefs, Ask history
src/theme/          Floodlit tokens (spec §30) and useTheme
```

## Checks

```bash
npx tsc --noEmit
npx expo-doctor
```
