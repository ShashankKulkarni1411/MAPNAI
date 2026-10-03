// O6 Building your brief: real progress steps while the first slate computes. After 6 s, Home opens on a
// skeleton and fills in when ready; failure or an empty slate opens Home in its fallback state.
import { router } from 'expo-router';
import { useEffect, useRef, useState } from 'react';
import { View } from 'react-native';

import { api } from '@/api/endpoints';
import { queryClient } from '@/api/hooks';
import { Glyph } from '@/components/Glyph';
import { OnboardingTop } from '@/components/OnboardingTop';
import { FormScreen } from '@/components/Screen';
import { Txt } from '@/components/Txt';
import { useSession } from '@/state/session';
import { useTheme } from '@/theme/useTheme';

export default function Building() {
  const { c } = useTheme();
  const s = useSession();
  const [step, setStep] = useState(0);
  const [follows, setFollows] = useState<number | null>(null);
  const left = useRef(false);

  useEffect(() => {
    const uid = s.userId!;
    const go = () => {
      if (left.current) return;
      left.current = true;
      s.advance('done');
      router.replace('/(tabs)');
    };
    const timeout = setTimeout(go, 6000);
    (async () => {
      try {
        const p = await api.profile(uid);
        setFollows(p.exposures.length);
        queryClient.setQueryData(['profile', uid], p);
        setStep(1);
        const d = await api.digest(uid, true);
        setStep(2);
        queryClient.setQueryData(['digest', uid], d);
        setStep(3);
      } catch {}
      setTimeout(go, 500);
    })();
    return () => clearTimeout(timeout);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const steps = [
    follows === null ? 'Mapping your follows…' : `Mapping ${follows} follow${follows === 1 ? '' : 's'}…`,
    'Finding today’s stories…',
    'Ranking your brief…',
  ];

  return (
    <FormScreen top={<OnboardingTop step={6} />}>
      <Txt v="screenTitle" accessibilityRole="header">Building your brief</Txt>
      <View style={{ gap: 14 }} accessibilityLiveRegion="polite">
        {steps.map((t, i) => (
          <View key={i} style={{ flexDirection: 'row', alignItems: 'center', gap: 10, opacity: step >= i ? 1 : 0.4 }}>
            <Glyph name={step > i ? 'check' : 'dots'} color={c.ink} />
            <Txt v="body">{t}</Txt>
          </View>
        ))}
      </View>
      <View style={{ gap: 4 }}>
        <Txt v="metaBold">Using</Txt>
        <Txt v="meta" muted>
          {s.swipes.likes.length} liked headline{s.swipes.likes.length === 1 ? '' : 's'}
          {follows !== null ? `, ${follows} follow${follows === 1 ? '' : 's'}` : ''}. You can change all of this in Profile.
        </Txt>
      </View>
    </FormScreen>
  );
}
