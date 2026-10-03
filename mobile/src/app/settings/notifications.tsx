// T2 Notifications: alert cap, quiet hours, time zone. Built: alert_prefs. Recap/suggestion pushes: Proposed.
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
import { useFeedback } from '@/state/feedback';

const HHMM = /^([01]\d|2[0-3]):[0-5]\d$/;

export default function NotificationSettings() {
  const uid = useUserId();
  const profile = useProfile();
  const [prefs, setPrefs] = useState<AlertPrefs>({ max_per_day: 3, quiet_start: '22:00', quiet_end: '07:00', tz: 'Asia/Kolkata' });
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

      <SectionTitle title="Which follows can alert me" />
      {alerting.length === 0 && <Txt v="body" muted>Alerts start when you follow something as Essential or Important.</Txt>}
      {alerting.map((e) => <Row key={e.key} title={e.name} sub={importance[e.weight].label} />)}

      <SectionTitle title="Recaps" sub="Recaps arrive in a later update." />
      <View style={{ flexDirection: 'row', alignItems: 'center', minHeight: 48 }}>
        <Txt v="body" style={{ flex: 1 }}>Weekly recap on Sunday</Txt>
        <Switch value={weekly} onValueChange={setWeekly} accessibilityLabel="Weekly recap on Sunday" />
      </View>
      <View style={{ flexDirection: 'row', alignItems: 'center', minHeight: 48 }}>
        <Txt v="body" style={{ flex: 1 }}>Daily recap at 21:00</Txt>
        <Switch value={daily} onValueChange={setDaily} accessibilityLabel="Daily recap at 21:00" />
      </View>
    </FormScreen>
  );
}
