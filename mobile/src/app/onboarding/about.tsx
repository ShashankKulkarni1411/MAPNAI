// O1 About you: create the persona, ask name and gender, get the demographic-use choice.
import { router } from 'expo-router';
import { useState } from 'react';
import { View } from 'react-native';

import { errorCopy } from '@/api/client';
import { api } from '@/api/endpoints';
import { Button } from '@/components/Button';
import { Field } from '@/components/Field';
import { OnboardingTop } from '@/components/OnboardingTop';
import { FormScreen } from '@/components/Screen';
import { Sheet } from '@/components/Sheet';
import { Txt } from '@/components/Txt';
import { Chip, InlineError } from '@/components/ui';
import { signOutEverywhere } from '@/lib/signOut';
import { useSession } from '@/state/session';
import { radius, space } from '@/theme/tokens';
import { useTheme } from '@/theme/useTheme';

const GENDERS = ['Woman', 'Man', 'Non-binary', 'Self-describe', 'Prefer not to say'];

export default function About() {
  const { c } = useTheme();
  const s = useSession();
  const [name, setName] = useState(s.name ?? '');
  const [gender, setGender] = useState<string | null>(s.gender && GENDERS.includes(s.gender) ? s.gender : s.gender ? 'Self-describe' : null);
  const [selfText, setSelfText] = useState(s.gender && !GENDERS.includes(s.gender) ? s.gender : '');
  const [demo, setDemo] = useState<boolean | null>(s.useDemographics);
  const [learn, setLearn] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const trimmed = name.trim();
  const ok = trimmed.length >= 1 && trimmed.length <= 40 && gender !== null && demo !== null;

  async function next() {
    setBusy(true);
    setError(null);
    try {
      let uid = s.userId;
      if (!uid) {
        const r = await api.createUser(trimmed);
        uid = r.user_id;
        if (s.email) await api.linkUser(s.email, uid);
      }
      // PATCH /v1/users/{id}/demographics is Proposed; kept on the device until it exists
      s.set({ userId: uid, name: trimmed, gender: gender === 'Self-describe' ? selfText.trim() || 'Self-describe' : gender, useDemographics: demo });
      s.advance('connected');
      router.push('/onboarding/connected');
    } catch (e) {
      setError(errorCopy(e, "Couldn't save. Try again."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <FormScreen
      top={<OnboardingTop step={1} right={<Button label="Sign out" variant="text" small onPress={signOutEverywhere} />} />}
      footer={<Button label="Continue" disabled={!ok} loading={busy} onPress={next} />}
    >
      <Txt v="screenTitle" accessibilityRole="header">First, a little about you</Txt>
      <Field label="Your name" value={name} onChangeText={setName} maxLength={40} autoComplete="given-name" textContentType="givenName" />
      <View style={{ gap: 8 }}>
        <Txt v="metaBold">Gender</Txt>
        <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8 }} accessibilityRole="radiogroup">
          {GENDERS.map((g) => <Chip key={g} label={g} selected={gender === g} onPress={() => setGender(g)} />)}
        </View>
        {gender === 'Self-describe' && <Field label="Describe your gender (optional)" value={selfText} onChangeText={setSelfText} maxLength={40} />}
      </View>
      <View style={{ backgroundColor: c.surface, borderRadius: radius.card, borderWidth: 1, borderColor: c.hairline, padding: space.lg, gap: space.md }}>
        <Txt v="body">Use my age group and gender to suggest topics until MAPNAI learns from my reading?</Txt>
        <View style={{ flexDirection: 'row', gap: 8, flexWrap: 'wrap' }}>
          <Chip label="Yes, use them" selected={demo === true} onPress={() => setDemo(true)} />
          <Chip label="No thanks" selected={demo === false} onPress={() => setDemo(false)} />
        </View>
        <Button label="Learn more" variant="text" small onPress={() => setLearn(true)} style={{ alignSelf: 'flex-start' }} />
      </View>
      {error && <InlineError text={error} onRetry={next} />}
      <Sheet visible={learn} onClose={() => setLearn(false)} title="How we use them">
        <Txt v="body">
          They only shape starting suggestions for topics and people you haven't picked. Your own choices and reading outweigh them
          within a few taps. They never decide must-know stories or alerts. Change this anytime in Profile.
        </Txt>
      </Sheet>
    </FormScreen>
  );
}
