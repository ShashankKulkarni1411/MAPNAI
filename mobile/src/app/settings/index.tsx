// T1 Settings. Interest controls live in Profile → What MAPNAI knows, so personalization has one home.
import Constants from 'expo-constants';
import { router } from 'expo-router';

import { API_MODE, API_URL } from '@/api/client';
import { Button } from '@/components/Button';
import { FormScreen } from '@/components/Screen';
import { Txt } from '@/components/Txt';
import { Row, TopBar } from '@/components/ui';
import { signOutEverywhere } from '@/lib/signOut';

export default function Settings() {
  return (
    <FormScreen top={<TopBar title="Settings" />}>
      <Row title="Account" onPress={() => router.push('/settings/account')} />
      <Row title="Notifications" onPress={() => router.push('/settings/notifications')} />
      <Row title="Privacy and data" onPress={() => router.push('/settings/privacy')} />
      <Row title="Appearance" onPress={() => router.push('/settings/appearance')} />
      <Row title="How MAPNAI works" onPress={() => router.push('/settings/how')} />
      <Row title="Help and feedback" onPress={() => router.push('/settings/help')} />
      <Txt v="meta" muted>MAPNAI {Constants.expoConfig?.version} · data: {API_MODE === 'mock' ? 'demo' : `${API_MODE} (${API_URL})`}</Txt>
      <Button label="Sign out" variant="secondary" onPress={signOutEverywhere} />
    </FormScreen>
  );
}
