// O5 Alerts and notifications: set expectations, then ask for push permission at the right moment.
// Device registration (POST /v1/users/{id}/devices) is Proposed; we only ask the OS for permission here.
import * as Localization from 'expo-localization';
import * as Notifications from 'expo-notifications';
import { router } from 'expo-router';
import { useState } from 'react';
import { Switch, View } from 'react-native';

import { errorCopy } from '@/api/client';
import { api } from '@/api/endpoints';
import { useProfile } from '@/api/hooks';
import { Button } from '@/components/Button';
import { Glyph } from '@/components/Glyph';
import { OnboardingTop } from '@/components/OnboardingTop';
import { FormScreen } from '@/components/Screen';
import { Txt } from '@/components/Txt';
import { InlineError, Pill, Segmented } from '@/components/ui';
import { useSession } from '@/state/session';
import { radius, space } from '@/theme/tokens';
import { useTheme } from '@/theme/useTheme';

export default function Alerts() {
  const { c } = useTheme();
  const s = useSession();
  const [max, setMax] = useState(3);
  const [weekly, setWeekly] = useState(true);
  const [daily, setDaily] = useState(false);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const tz = Localization.getCalendars()[0]?.timeZone ?? 'Asia/Kolkata';
  const profile = useProfile();
  const noFollows = profile.data ? !profile.data.exposures.some((e) => e.weight >= 2) : false;

  async function next(askPush: boolean) {
    setBusy(true);
    setError(null);
    try {
      await api.patchAlertPrefs(s.userId!, { max_per_day: max, quiet_start: '22:00', quiet_end: '07:00', tz });
      // Weekly / daily recap preferences are Proposed fields; kept local for now
      if (askPush) {
        const res = await Notifications.requestPermissionsAsync().catch(() => ({ granted: false }));
        if (!res.granted) {
          setNote('You can turn alerts on later in Settings.');
          await new Promise((r) => setTimeout(r, 1200));
        }
      }
      s.advance('building');
      router.push('/onboarding/building');
    } catch (e) {
      setError(errorCopy(e, "Couldn't save. Try again."));
    } finally {
      setBusy(false);
    }
  }

  const fact = (t: string) => (
    <View style={{ flexDirection: 'row', gap: 10, alignItems: 'flex-start' }}>
      <Glyph name="check" color={c.ink} />
      <Txt v="body" style={{ flex: 1 }}>{t}</Txt>
    </View>
  );

  return (
    <FormScreen
      top={<OnboardingTop step={5} />}
      footer={
        <>
          <Button label="Turn on alerts" loading={busy} onPress={() => next(true)} />
          <Button label="Not now" variant="text" onPress={() => next(false)} />
        </>
      }
    >
      <Txt v="screenTitle" accessibilityRole="header">Alerts only for what matters</Txt>
      <View accessibilityLabel="Sample alert: Virat Kohli ruled out of first Test. You follow Virat Kohli, Essential. Major, 9 sources."
        style={{ backgroundColor: c.surface, borderRadius: radius.card, borderWidth: 1, borderColor: c.hairline, padding: space.lg, gap: 6 }}>
        <Pill label="Major" kind="impactFilled" />
        <Txt v="metaBold">Virat Kohli: ruled out of first Test with hamstring injury</Txt>
        <Txt v="meta" muted>You follow Virat Kohli (Essential) · Major · 9 sources</Txt>
      </View>
      {noFollows
        ? <Txt v="body">Alerts start when you follow something as Essential or Important.</Txt>
        : (
          <View style={{ gap: 10 }}>
            {fact("Only big news about what's Essential to you")}
            {fact(`At most ${max} a day, one per story`)}
            {fact('Never between 22:00 and 07:00 (your time)')}
          </View>
        )}
      <View style={{ gap: 8 }}>
        <Txt v="metaBold">Most alerts per day</Txt>
        <Segmented label="Most alerts per day" value={max} onChange={setMax} options={[1, 2, 3, 4, 5].map((n) => ({ label: String(n), value: n }))} />
      </View>
      <View style={{ flexDirection: 'row', alignItems: 'center', minHeight: 48 }}>
        <Txt v="body" style={{ flex: 1 }}>Weekly recap on Sunday</Txt>
        <Switch value={weekly} onValueChange={setWeekly} accessibilityLabel="Weekly recap on Sunday" />
      </View>
      <View style={{ flexDirection: 'row', alignItems: 'center', minHeight: 48 }}>
        <Txt v="body" style={{ flex: 1 }}>Daily recap at 21:00</Txt>
        <Switch value={daily} onValueChange={setDaily} accessibilityLabel="Daily recap at 21:00" />
      </View>
      {note && <Txt v="meta" accessibilityLiveRegion="polite">{note}</Txt>}
      {error && <InlineError text={error} />}
    </FormScreen>
  );
}
