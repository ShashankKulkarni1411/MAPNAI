// A6 Reset password: email → code → new password on one screen. Backend is Proposed; in mock mode it
// shows the steps but cannot change a stored password.
import { router } from 'expo-router';
import { useState } from 'react';

import { API_MODE } from '@/api/client';
import { Button } from '@/components/Button';
import { Field } from '@/components/Field';
import { FormScreen } from '@/components/Screen';
import { Txt } from '@/components/Txt';
import { Progress, TopBar } from '@/components/ui';
import { isEmail, passwordProblem } from '@/state/authDraft';

export default function Reset() {
  const [step, setStep] = useState(1);
  const [email, setEmail] = useState('');
  const [code, setCode] = useState('');
  const [pw, setPw] = useState('');
  const pwErr = pw ? passwordProblem(pw) : null;

  return (
    <FormScreen
      top={<TopBar title="Reset password" />}
      footer={
        step === 1 ? <Button label="Send code" disabled={!isEmail(email)} onPress={() => setStep(2)} />
        : step === 2 ? <Button label="Continue" disabled={code.length !== 6} onPress={() => setStep(3)} />
        : <Button label="Set new password" disabled={!pw || !!pwErr} onPress={() => router.replace('/(auth)/sign-in')} />
      }
    >
      <Progress step={step} total={3} />
      <Txt v="screenTitle" accessibilityRole="header">Reset your password</Txt>
      {API_MODE !== 'live' && <Txt v="meta" muted>Demo mode: this flow needs the auth service, so the password won’t change.</Txt>}
      {step === 1 && <Field label="Email" value={email} onChangeText={setEmail} autoCapitalize="none" keyboardType="email-address" />}
      {step === 2 && <Field label="Code" value={code} onChangeText={(t) => setCode(t.replace(/\D/g, '').slice(0, 6))} keyboardType="number-pad" autoComplete="one-time-code" />}
      {step === 3 && <Field label="New password" value={pw} onChangeText={setPw} secureToggle error={pwErr} autoComplete="new-password" />}
    </FormScreen>
  );
}
