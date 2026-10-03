// T3 Privacy and data (MVP basic). Export and the consent history need the Proposed auth/users service.
import { Alert, Switch, View } from 'react-native';

import { Button } from '@/components/Button';
import { FormScreen } from '@/components/Screen';
import { Txt } from '@/components/Txt';
import { SectionTitle, TopBar } from '@/components/ui';
import { useAskHistory } from '@/state/askHistory';
import { useSession } from '@/state/session';
import { useFeedback } from '@/state/feedback';

const STORED: [string, string, string][] = [
  ['Email, birth year, consents', 'Your account and the 18+ check', 'Until you delete your account'],
  ['Follows, topics, style, alert settings', 'Personalizing your brief and alerts', 'Until you change or delete them'],
  ['Reading history', 'For you picks', 'Last 200 stories'],
  ['Feedback and impressions', 'Tuning must-know and suggestions', '13 months, then aggregated'],
  ['Ask questions', 'Your recent questions', 'This device only'],
];

export default function Privacy() {
  const s = useSession();
  const clearAsk = useAskHistory((x) => x.clear);
  return (
    <FormScreen top={<TopBar title="Privacy and data" />}>
      <SectionTitle title="What MAPNAI stores" />
      {STORED.map(([what, why, kept]) => (
        <View key={what} style={{ gap: 2, paddingVertical: 6 }}>
          <Txt v="metaBold">{what}</Txt>
          <Txt v="meta" muted>{why} · {kept}</Txt>
        </View>
      ))}
      <SectionTitle title="Controls" />
      <View style={{ flexDirection: 'row', alignItems: 'center', minHeight: 48 }}>
        <Txt v="body" style={{ flex: 1 }}>Use my age group and gender for suggestions</Txt>
        <Switch value={!!s.useDemographics} onValueChange={(v) => s.set({ useDemographics: v })} accessibilityLabel="Use my age group and gender for suggestions" />
      </View>
      <Button label="Clear Ask history" variant="secondary" onPress={() => { clearAsk(); useFeedback.getState().showToast('Ask history cleared'); }} />
      <Button label="Download my data" variant="secondary" disabled />
      <Txt v="meta" muted>Download arrives with account services in a later update.</Txt>
      <Button label="Delete account" variant="destructive" onPress={() => Alert.alert('Delete account', 'Account deletion arrives with account services in a later update.')} />
    </FormScreen>
  );
}
