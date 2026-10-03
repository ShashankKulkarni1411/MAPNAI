// A5 Sign in. Always the generic error; 5 failures lock for 15 minutes; unverified goes to A4.
import { router } from 'expo-router';
import { useState } from 'react';

import { ApiError, errorCopy } from '@/api/client';
import { api } from '@/api/endpoints';
import { Button } from '@/components/Button';
import { Field } from '@/components/Field';
import { FormScreen } from '@/components/Screen';
import { Txt } from '@/components/Txt';
import { InlineError, TopBar } from '@/components/ui';
import { onboardingRoute, useSession } from '@/state/session';

let failures = 0;
let lockedUntil = 0;

export default function SignIn() {
  const session = useSession();
  const [email, setEmail] = useState(session.email ?? '');
  const [pw, setPw] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    if (Date.now() < lockedUntil) {
      setError('Too many attempts. Try again in 15 minutes.');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const r = await api.login(email.trim().toLowerCase(), pw);
      failures = 0;
      // a different account on this device starts with a clean session
      const same = session.email === email.trim().toLowerCase();
      session.set({
        ...(same ? {} : { userId: null, onboarding: 'about', name: null, context: [], swipes: { likes: [], dislikes: [], likedEntities: [] } }),
        email: email.trim().toLowerCase(), accessToken: r.access_token, refreshToken: r.refresh_token, emailVerified: true,
        userId: r.user_id ?? (same ? session.userId : null),
      });
      const next = r.user_id ? (same ? session.onboarding : 'done') : 'about';
      if (r.user_id && !same) session.set({ onboarding: 'done' });
      router.replace(onboardingRoute(next) as never);
    } catch (e) {
      if (e instanceof ApiError && e.status === 403) {
        session.set({ email: email.trim().toLowerCase() });
        router.push('/(auth)/verify');
        return;
      }
      if (e instanceof ApiError && e.offline) setError(errorCopy(e));
      else {
        failures++;
        if (failures >= 5) lockedUntil = Date.now() + 15 * 60_000;
        setError('Email or password is incorrect.');
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <FormScreen
      top={<TopBar title="Sign in" />}
      footer={
        <>
          <Button label="Sign in" disabled={!email || !pw} loading={busy} onPress={submit} />
          <Button label="Create account" variant="text" onPress={() => router.replace('/(auth)/create')} />
        </>
      }
    >
      <Txt v="screenTitle" accessibilityRole="header">Welcome back</Txt>
      <Field label="Email" value={email} onChangeText={setEmail} autoCapitalize="none" keyboardType="email-address" autoComplete="email" />
      <Field label="Password" value={pw} onChangeText={setPw} secureToggle autoComplete="current-password" textContentType="password" />
      {error && <InlineError text={error} />}
      <Button label="Forgot password?" variant="text" onPress={() => router.push('/(auth)/reset')} style={{ alignSelf: 'flex-start' }} />
    </FormScreen>
  );
}
