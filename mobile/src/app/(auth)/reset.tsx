// A6 Reset password: email → code → new password on one screen. Live mode uses the API's reset endpoints;
// the other modes use the demo accounts on the device (code 123456).
import { router } from 'expo-router';
import { useState } from 'react';

import { API_MODE, errorCopy } from '@/api/client';
import { api } from '@/api/endpoints';
import { Button } from '@/components/Button';
import { Field } from '@/components/Field';
import { FormScreen } from '@/components/Screen';
import { Txt } from '@/components/Txt';
import { InlineError, Progress, TopBar } from '@/components/ui';
import { isEmail, passwordProblem } from '@/state/authDraft';
import { useFeedback } from '@/state/feedback';

export default function Reset() {
  const [step, setStep] = useState(1);
  const [email, setEmail] = useState('');
  const [code, setCode] = useState('');
  const [pw, setPw] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pwErr = pw ? passwordProblem(pw) : null;

  async function run(fn: () => Promise<unknown>, fallback: string, next: () => void) {
    setBusy(true);
    setError(null);
    try {
      await fn();
      next();
    } catch (e) {
      setError(errorCopy(e, fallback));
    } finally {
      setBusy(false);
    }
  }

  const sendCode = () =>
    run(() => api.requestReset(email.trim().toLowerCase()), "Couldn't send the code. Try again.", () => setStep(2));
  const setPassword = () =>
    run(() => api.confirmReset(email.trim().toLowerCase(), code, pw), "That code didn't work. Send a new code and try again.", () => {
      useFeedback.getState().showToast('Password changed. Sign in with your new password.');
      router.replace('/(auth)/sign-in');
    });

  return (
    <FormScreen
      top={<TopBar title="Reset password" />}
      footer={
        step === 1 ? <Button label="Send code" disabled={!isEmail(email)} loading={busy} onPress={sendCode} />
        : step === 2 ? <Button label="Continue" disabled={code.length !== 6} onPress={() => setStep(3)} />
        : <Button label="Set new password" disabled={!pw || !!pwErr} loading={busy} onPress={setPassword} />
      }
    >
      <Progress step={step} total={3} />
      <Txt v="screenTitle" accessibilityRole="header">Reset your password</Txt>
      {step === 2 && <Txt v="body" muted>If {email.trim()} has an account, we sent it a 6-digit code.</Txt>}
      {API_MODE !== 'live' && step === 2 && <Txt v="meta" muted>Demo mode: use 123456.</Txt>}
      {step === 1 && <Field label="Email" value={email} onChangeText={setEmail} autoCapitalize="none" keyboardType="email-address" />}
      {step === 2 && <Field label="Code" value={code} onChangeText={(t) => setCode(t.replace(/\D/g, '').slice(0, 6))} keyboardType="number-pad" autoComplete="one-time-code" />}
      {step === 3 && <Field label="New password" value={pw} onChangeText={setPw} secureToggle error={pwErr} autoComplete="new-password" />}
      {error && <InlineError text={error} />}
      {step === 3 && error && <Button label="Back to code" variant="text" onPress={() => { setStep(2); setError(null); }} style={{ alignSelf: 'flex-start' }} />}
    </FormScreen>
  );
}
