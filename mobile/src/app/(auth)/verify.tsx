// A4 Verify email: 6-digit code, resend after 30 s, 3 wrong tries then a new code is required.
import { router } from 'expo-router';
import { useEffect, useState } from 'react';

import { API_MODE, errorCopy } from '@/api/client';
import { api } from '@/api/endpoints';
import { Button } from '@/components/Button';
import { Field } from '@/components/Field';
import { FormScreen } from '@/components/Screen';
import { Txt } from '@/components/Txt';
import { TopBar } from '@/components/ui';
import { onboardingRoute, useSession } from '@/state/session';

export default function Verify() {
  const session = useSession();
  const [code, setCode] = useState('');
  const [tries, setTries] = useState(0);
  const [wait, setWait] = useState(30);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (wait <= 0) return;
    const t = setTimeout(() => setWait((w) => w - 1), 1000);
    return () => clearTimeout(t);
  }, [wait]);

  async function verify() {
    if (!session.email) return;
    setBusy(true);
    setError(null);
    try {
      const r = await api.verify(session.email, code);
      session.set({ accessToken: r.access_token, refreshToken: r.refresh_token, emailVerified: true, userId: r.user_id ?? session.userId });
      router.replace((r.user_id ? '/(tabs)' : onboardingRoute(session.onboarding)) as never);
    } catch (e) {
      const n = tries + 1;
      setTries(n);
      setError(n >= 3 ? 'Too many tries. Send a new code.' : errorCopy(e, "That code didn't work. Check it and try again."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <FormScreen
      top={<TopBar title="Verify email" />}
      footer={
        <>
          <Button label="Verify" disabled={code.length !== 6 || tries >= 3} loading={busy} onPress={verify} />
          <Button label={wait > 0 ? `Resend code in ${wait}s` : 'Resend code'} variant="text" disabled={wait > 0}
            onPress={() => {
              setWait(30); setTries(0); setCode(''); setError(null);
              if (session.email) api.resend(session.email).catch((e) => setError(errorCopy(e, "Couldn't send a new code. Try again.")));
            }} />
        </>
      }
    >
      <Txt v="screenTitle" accessibilityRole="header">Check your email</Txt>
      <Txt v="body" muted>We sent a 6-digit code to {session.email ?? 'your email'}. It expires in 10 minutes.</Txt>
      {API_MODE !== 'live' && <Txt v="meta" muted>Demo mode: use 123456.</Txt>}
      <Field label="Code" value={code} onChangeText={(t) => setCode(t.replace(/\D/g, '').slice(0, 6))} keyboardType="number-pad"
        autoComplete="one-time-code" textContentType="oneTimeCode" maxLength={6} error={error} />
      <Button label="Change email" variant="text" onPress={() => router.replace('/(auth)/create')} style={{ alignSelf: 'flex-start' }} />
    </FormScreen>
  );
}
