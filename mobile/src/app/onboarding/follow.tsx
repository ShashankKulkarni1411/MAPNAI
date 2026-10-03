// O4 Follow: the most important input. Continue sends PATCH exposures, then the O3 swipes (in that order,
// so the Beta priors stay correct: topics, then follows, then swipes).
import { router } from 'expo-router';
import { useState } from 'react';

import { ApiError, errorCopy } from '@/api/client';
import { api } from '@/api/endpoints';
import { Button } from '@/components/Button';
import { Connection } from '@/components/follow/ConnectionSheet';
import { defaultRoleFor, FollowPicker } from '@/components/follow/FollowPicker';
import { OnboardingTop } from '@/components/OnboardingTop';
import { FormScreen } from '@/components/Screen';
import { Txt } from '@/components/Txt';
import { InlineError } from '@/components/ui';
import { useSession } from '@/state/session';

// Until GET /v1/entities/suggested exists (Proposed), offer a small static list per topic
const POPULAR = {
  sports: [
    { key: 'virat kohli', name: 'Virat Kohli' }, { key: 'india test team', name: 'India Test team' },
    { key: 'ipl', name: 'IPL' }, { key: 'manchester city', name: 'Manchester City' }, { key: 'fifa', name: 'FIFA' },
  ],
  film: [
    { key: 'shah rukh khan', name: 'Shah Rukh Khan' }, { key: 'yash raj films', name: 'Yash Raj Films' },
    { key: 'netflix india', name: 'Netflix India' }, { key: 'oscars', name: 'Oscars' },
  ],
};

export default function Follow() {
  const s = useSession();
  const [tray, setTray] = useState<Connection[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const role = defaultRoleFor(s.context);

  async function next(skip: boolean) {
    setBusy(true);
    setError(null);
    let current = tray;
    try {
      if (!skip && current.length) {
        // An unknown key (404) is dropped with a note, and the rest still save
        for (;;) {
          try {
            await api.patchExposures(s.userId!, current.map(({ key, role, weight }) => ({ key, role, weight })));
            break;
          } catch (e) {
            const bad = e instanceof ApiError && e.status === 404 ? current.find((t) => e.message.includes(t.key)) : undefined;
            if (!bad) throw e;
            setError(`Couldn't add ${bad.name}.`);
            current = current.filter((t) => t.key !== bad.key);
            setTray(current);
            if (!current.length) break;
          }
        }
      }
      const { likes, dislikes } = s.swipes;
      if (likes.length || dislikes.length) {
        await api.onboarding(s.userId!, likes, dislikes).catch(() => {}); // a failed swipe post doesn't block setup
      }
      s.advance('alerts');
      router.push('/onboarding/alerts');
    } catch (e) {
      setError(errorCopy(e, "Couldn't save your follows. Try again."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <FormScreen
      top={<OnboardingTop step={4} right={<Button label="Skip for now" variant="text" small onPress={() => next(true)} />} />}
      footer={<Button label={tray.length ? `Continue with ${tray.length}` : 'Continue'} loading={busy} onPress={() => next(false)} />}
    >
      <Txt v="screenTitle" accessibilityRole="header">Who and what do you follow?</Txt>
      <Txt v="body" muted>Follows decide what becomes must-know for you, and what can alert you.</Txt>
      <FollowPicker
        tray={tray}
        setTray={setTray}
        defaultRole={role}
        suggestions={[
          { title: 'From stories you liked', items: s.swipes.likedEntities },
          { title: 'Popular in Sports', items: POPULAR.sports },
          { title: 'Popular in Film', items: POPULAR.film },
        ]}
      />
      {error && <InlineError text={error} />}
    </FormScreen>
  );
}
