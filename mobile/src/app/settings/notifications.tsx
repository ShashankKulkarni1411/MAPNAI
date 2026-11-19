// T2 Notifications: alert cap, quiet hours, time zone, breaking news (hit news for you / for everyone), push on
// this device. Built: alert_prefs, push_tokens. Recap / suggestion pushes: Proposed (the recaps are built: Home, R1).
import * as Localization from 'expo-localization';
import { useEffect, useState } from 'react';
import { Switch, View } from 'react-native';

import { api } from '@/api/endpoints';
import { useProfile, useUserId } from '@/api/hooks';
import type { AlertPrefs } from '@/api/types';
import { Field } from '@/components/Field';
import { FormScreen } from '@/components/Screen';
import { Txt } from '@/components/Txt';
import { Button } from '@/components/Button';
import { Row, Segmented, SectionTitle, TopBar } from '@/components/ui';
import { importance } from '@/lib/labels';
import { askPushPermission, inExpoGo, pushSupported, registerPush } from '@/lib/push';
import { useFeedback } from '@/state/feedback';

const HHMM = /^([01]\d|2[0-3]):[0-5]\d$/;

export default function NotificationSettings() {
  const uid = useUserId();
  const profile = useProfile();
  const [prefs, setPrefs] = useState<AlertPrefs>({
    max_per_day: 3, quiet_start: '22:00', quiet_end: '07:00', tz: 'Asia/Kolkata', breaking_for_you: true, breaking_global: false,
  });
  const [pushOn, setPushOn] = useState<boolean | null>(null);
  const [weekly, setWeekly] = useState(true);
  const [daily, setDaily] = useState(false);
  const deviceTz = Localization.getCalendars()[0]?.timeZone ?? 'Asia/Kolkata';
  useEffect(() => { if (profile.data?.alert_prefs) setPrefs(profile.data.alert_prefs); }, [profile.data]);

  async function save(p: Partial<AlertPrefs>) {
    const prev = prefs;
    setPrefs({ ...prefs, ...p });
    try {
      await api.patchAlertPrefs(uid, p);
    } catch {
      setPrefs(prev); // toggles revert on failure
      useFeedback.getState().showToast("Couldn't save. Try again.");
    }
  }

  const alerting = (profile.data?.exposures ?? []).filter((e) => e.weight >= 2);

  async function turnOnPush() {
    const ok = await askPushPermission();
    setPushOn(ok && !!(await registerPush(uid)));
    if (!ok) useFeedback.getState().showToast('Allow notifications for MAPNAI in your phone settings.');
  }

  return (
    <FormScreen top={<TopBar title="Notifications" />}>
      <SectionTitle title="Alerts" sub="Only big news about what's Essential or Important to you, one per story." />
      <Txt v="metaBold">Most alerts per day</Txt>
      <Segmented label="Most alerts per day" value={prefs.max_per_day} onChange={(n) => save({ max_per_day: n })}
        options={[1, 2, 3, 4, 5].map((n) => ({ label: String(n), value: n }))} />
      <View style={{ flexDirection: 'row', gap: 10 }}>
        <View style={{ flex: 1 }}>
          <Field label="Quiet from" value={prefs.quiet_start} maxLength={5} onChangeText={(t) => setPrefs({ ...prefs, quiet_start: t })}
            onBlur={() => HHMM.test(prefs.quiet_start) && save({ quiet_start: prefs.quiet_start })} error={HHMM.test(prefs.quiet_start) ? null : 'Use HH:MM'} />
        </View>
        <View style={{ flex: 1 }}>
          <Field label="Until" value={prefs.quiet_end} maxLength={5} onChangeText={(t) => setPrefs({ ...prefs, quiet_end: t })}
            onBlur={() => HHMM.test(prefs.quiet_end) && save({ quiet_end: prefs.quiet_end })} error={HHMM.test(prefs.quiet_end) ? null : 'Use HH:MM'} />
        </View>
      </View>
      <Row title="Time zone" sub={prefs.tz} right={prefs.tz !== deviceTz ? <Button label="Use this device's" variant="text" small onPress={() => save({ tz: deviceTz })} /> : undefined} />

      <SectionTitle title="Breaking news" sub="Stories many outlets are reporting at once. They count towards your daily limit." />
      <View style={{ flexDirection: 'row', alignItems: 'center', minHeight: 48 }}>
        <Txt v="body" style={{ flex: 1 }}>Breaking news about what I follow</Txt>
        <Switch value={prefs.breaking_for_you ?? true} onValueChange={(v) => save({ breaking_for_you: v })}
          accessibilityLabel="Breaking news about what I follow" />
      </View>
      <View style={{ flexDirection: 'row', alignItems: 'center', minHeight: 48 }}>
        <Txt v="body" style={{ flex: 1 }}>All major breaking news (at most 2 a day)</Txt>
        <Switch value={prefs.breaking_global ?? false} onValueChange={(v) => save({ breaking_global: v })}
          accessibilityLabel="All major breaking news, at most 2 a day" />
      </View>

      <SectionTitle title="This device" />
      {pushSupported ? (
        <Row title="Push notifications" sub={pushOn ? 'On: alerts arrive on this phone' : 'Alerts show in the app; turn this on to get them as notifications'}
          right={pushOn ? undefined : <Button label="Turn on" variant="text" small onPress={turnOnPush} />} />
      ) : (
        <Txt v="body" muted>{inExpoGo ? 'Push notifications need the installed app, not Expo Go.' : 'Push notifications are available in the phone app.'}</Txt>
      )}

      <SectionTitle title="Which follows can alert me" />
      {alerting.length === 0 && <Txt v="body" muted>Alerts start when you follow something as Essential or Important.</Txt>}
      {alerting.map((e) => <Row key={e.key} title={e.name} sub={importance[e.weight].label} />)}

      <SectionTitle title="Recaps" sub="Recaps are on Home. Notifications for them arrive in a later update." />
      <View style={{ flexDirection: 'row', alignItems: 'center', minHeight: 48 }}>
        <Txt v="body" style={{ flex: 1 }}>Weekly recap on Sunday at 22:00</Txt>
        <Switch value={weekly} onValueChange={setWeekly} accessibilityLabel="Weekly recap on Sunday at 22:00" />
      </View>
      <View style={{ flexDirection: 'row', alignItems: 'center', minHeight: 48 }}>
        <Txt v="body" style={{ flex: 1 }}>Daily recap of yesterday at 07:00</Txt>
        <Switch value={daily} onValueChange={setDaily} accessibilityLabel="Daily recap of yesterday at 07:00" />
      </View>
    </FormScreen>
  );
}
