// A3 Date of birth and consent. Only the birth year is kept; under 18 goes to A7 and nothing is stored.
import AsyncStorage from '@react-native-async-storage/async-storage';
import { router } from 'expo-router';
import { useEffect, useState } from 'react';
import { Linking, Pressable, View } from 'react-native';

import { api } from '@/api/endpoints';
import { ApiError, errorCopy } from '@/api/client';
import { Button } from '@/components/Button';
import { Field } from '@/components/Field';
import { Glyph } from '@/components/Glyph';
import { FormScreen } from '@/components/Screen';
import { Txt } from '@/components/Txt';
import { InlineError, TopBar } from '@/components/ui';
import { ELIGIBILITY_LOCK_KEY, useAuthDraft } from '@/state/authDraft';
import { useSession } from '@/state/session';
import { radius } from '@/theme/tokens';
import { useTheme } from '@/theme/useTheme';

function age(d: number, m: number, y: number, now = new Date()) {
  let a = now.getFullYear() - y;
  if (now.getMonth() + 1 < m || (now.getMonth() + 1 === m && now.getDate() < d)) a--;
  return a;
}

export default function Dob() {
  const { c } = useTheme();
  const draft = useAuthDraft();
  const setSession = useSession((s) => s.set);
  const [d, setD] = useState('');
  const [m, setM] = useState('');
  const [y, setY] = useState('');
  const [agreed, setAgreed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [locked, setLocked] = useState(false);

  useEffect(() => {
    AsyncStorage.getItem(ELIGIBILITY_LOCK_KEY).then((v) => setLocked(!!v && Number(v) > Date.now())).catch(() => {});
  }, []);

  const dd = Number(d), mm = Number(m), yy = Number(y);
  const valid = dd >= 1 && dd <= 31 && mm >= 1 && mm <= 12 && yy >= 1900 && yy <= new Date().getFullYear();
  const canSubmit = valid && agreed && !locked && !!draft.email;

  async function submit() {
    if (age(dd, mm, yy) < 18) {
      await AsyncStorage.setItem(ELIGIBILITY_LOCK_KEY, String(Date.now() + 24 * 3600_000)).catch(() => {});
      draft.set({ email: '', password: '' });
      router.replace('/(auth)/not-eligible');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api.register(draft.email, draft.password, yy);
      setSession({ email: draft.email, birthYear: yy, emailVerified: false });
      router.push('/(auth)/verify');
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) setError('An account with this email exists. Sign in?');
      else setError(errorCopy(e, "Couldn't create your account. Try again."));
    } finally {
      setBusy(false); // network errors keep the entered values
    }
  }

  return (
    <FormScreen top={<TopBar title="Create account" />}
      footer={<Button label="Create account" disabled={!canSubmit} loading={busy} onPress={submit} />}>
      <Txt v="screenTitle" accessibilityRole="header">When were you born?</Txt>
      <Txt v="body" muted>MAPNAI is for adults. We keep only your birth year.</Txt>
      {locked ? (
        <InlineError text="Date entry is unavailable on this device for now." />
      ) : (
        <View style={{ flexDirection: 'row', gap: 10 }}>
          <View style={{ flex: 1 }}><Field label="Day" value={d} onChangeText={setD} keyboardType="number-pad" maxLength={2} placeholder="DD" /></View>
          <View style={{ flex: 1 }}><Field label="Month" value={m} onChangeText={setM} keyboardType="number-pad" maxLength={2} placeholder="MM" /></View>
          <View style={{ flex: 1.4 }}><Field label="Year" value={y} onChangeText={setY} keyboardType="number-pad" maxLength={4} placeholder="YYYY" /></View>
        </View>
      )}
      <Pressable onPress={() => setAgreed((a) => !a)} accessibilityRole="checkbox" accessibilityState={{ checked: agreed }}
        style={{ flexDirection: 'row', gap: 12, alignItems: 'center', minHeight: 44 }}>
        <View style={{ width: 24, height: 24, borderRadius: 6, borderWidth: 2, borderColor: c.ink, backgroundColor: agreed ? c.ink : 'transparent', alignItems: 'center', justifyContent: 'center' }}>
          {agreed && <Glyph name="check" size={16} color={c.bg} />}
        </View>
        <Txt v="body" style={{ flex: 1 }}>I agree to the Terms and Privacy Policy</Txt>
      </Pressable>
      <Pressable onPress={() => Linking.openURL('https://example.com/mapnai/privacy')} accessibilityRole="link" style={{ minHeight: 44, justifyContent: 'center' }}>
        <Txt v="metaBold" style={{ textDecorationLine: 'underline' }}>What we collect and why</Txt>
      </Pressable>
      {error && (
        <View style={{ borderRadius: radius.card, gap: 8 }}>
          <InlineError text={error} />
          {error.startsWith('An account') && <Button label="Sign in" variant="secondary" small onPress={() => router.replace('/(auth)/sign-in')} />}
        </View>
      )}
    </FormScreen>
  );
}
