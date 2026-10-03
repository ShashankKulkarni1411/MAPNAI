// O2 What brings you here: connection context (sets the default role in O4) and Sports/Film weights.
import { router } from 'expo-router';
import { useState } from 'react';
import { View } from 'react-native';

import { errorCopy } from '@/api/client';
import { api } from '@/api/endpoints';
import { Button } from '@/components/Button';
import { OnboardingTop } from '@/components/OnboardingTop';
import { FormScreen } from '@/components/Screen';
import { Txt } from '@/components/Txt';
import { Chip, InlineError, Segmented } from '@/components/ui';
import { topicLevels } from '@/lib/labels';
import { Context, useSession } from '@/state/session';

const CONTEXTS: { key: Context; label: string }[] = [
  { key: 'fan', label: "I'm a fan" },
  { key: 'cover', label: 'I cover it (journalist, creator, analyst)' },
  { key: 'fantasy', label: 'I play fantasy or prediction games' },
  { key: 'work', label: 'I work in sports or film' },
  { key: 'invest', label: 'I invest in sports or media' },
];

export default function Connected() {
  const s = useSession();
  const [ctx, setCtx] = useState<Context[]>(s.context);
  const [sports, setSports] = useState(0.6);
  const [film, setFilm] = useState(0.6);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const bothOff = sports === 0 && film === 0;

  async function save(skip = false) {
    const topics = skip ? { sports: 0.6, entertainment_movies: 0.6 } : { sports, entertainment_movies: film };
    setBusy(true);
    setError(null);
    try {
      await api.patchTopics(s.userId!, topics);
      s.set({ context: skip ? ['fan'] : ctx.length ? ctx : ['fan'] });
      s.advance('swipe');
      router.push('/onboarding/swipe');
    } catch (e) {
      setError(errorCopy(e, "Couldn't save. Try again."));
    } finally {
      setBusy(false);
    }
  }

  const toggle = (k: Context) => setCtx((c) => (c.includes(k) ? c.filter((x) => x !== k) : [...c, k]));
  const levels = topicLevels.map((l) => ({ label: l.label, value: l.value }));

  return (
    <FormScreen
      top={<OnboardingTop step={2} right={<Button label="Skip" variant="text" small onPress={() => save(true)} />} />}
      footer={<Button label="Continue" disabled={bothOff} loading={busy} onPress={() => save(false)} />}
    >
      <Txt v="screenTitle" accessibilityRole="header">What brings you here?</Txt>
      <View style={{ gap: 8 }}>
        <Txt v="metaBold">How are you connected to sports and film?</Txt>
        <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8 }}>
          {CONTEXTS.map((c) => <Chip key={c.key} label={c.label} selected={ctx.includes(c.key)} onPress={() => toggle(c.key)} />)}
        </View>
      </View>
      <View style={{ gap: 10 }}>
        <Txt v="metaBold">How much do you want?</Txt>
        <Txt v="body">Sports</Txt>
        <Segmented label="Sports" value={sports} onChange={setSports} options={levels} />
        <Txt v="body">Film</Txt>
        <Segmented label="Film" value={film} onChange={setFilm} options={levels} />
        {bothOff && <Txt v="meta" accessibilityLiveRegion="polite">Pick at least one, or choose Some for both.</Txt>}
        <Txt v="meta" muted>Other news appears only when it involves what you follow.</Txt>
      </View>
      {error && <InlineError text={error} />}
    </FormScreen>
  );
}
