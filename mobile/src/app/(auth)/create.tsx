// A2 Create account
import { router } from 'expo-router';
import { useState } from 'react';

import { Button } from '@/components/Button';
import { Field } from '@/components/Field';
import { FormScreen } from '@/components/Screen';
import { Txt } from '@/components/Txt';
import { TopBar } from '@/components/ui';
import { isEmail, passwordProblem, passwordStrength, useAuthDraft } from '@/state/authDraft';

export default function CreateAccount() {
  const draft = useAuthDraft();
  const [email, setEmail] = useState(draft.email);
  const [pw, setPw] = useState(draft.password);
  const [touched, setTouched] = useState(false);
  const emailErr = touched && email && !isEmail(email) ? 'Enter a valid email address.' : null;
  const pwErr = touched && pw ? passwordProblem(pw) : null;
  const ok = isEmail(email) && !passwordProblem(pw);

  return (
    <FormScreen
      top={<TopBar title="Create account" />}
      footer={
        <>
          <Button label="Continue" disabled={!ok} onPress={() => { draft.set({ email: email.trim().toLowerCase(), password: pw }); router.push('/(auth)/dob'); }} />
          <Button label="Sign in instead" variant="text" onPress={() => router.replace('/(auth)/sign-in')} />
        </>
      }
    >
      <Txt v="screenTitle" accessibilityRole="header">Create your account</Txt>
      <Field label="Email" value={email} onChangeText={setEmail} onBlur={() => setTouched(true)} autoCapitalize="none"
        autoComplete="email" keyboardType="email-address" textContentType="emailAddress" error={emailErr} />
      <Field label="Password" value={pw} onChangeText={(t) => { setPw(t); setTouched(true); }} secureToggle
        autoComplete="new-password" textContentType="newPassword" error={pwErr}
        hint={pw ? `Strength: ${passwordStrength(pw)}` : 'At least 8 characters.'} />
    </FormScreen>
  );
}
