// A7 Not eligible. No record is kept.
import { router } from 'expo-router';

import { Button } from '@/components/Button';
import { FormScreen } from '@/components/Screen';
import { Txt } from '@/components/Txt';

export default function NotEligible() {
  return (
    <FormScreen footer={<Button label="Close" onPress={() => router.replace('/(auth)/welcome')} />}>
      <Txt v="screenTitle" accessibilityRole="header">MAPNAI is for adults for now.</Txt>
      <Txt v="body" muted>We haven’t saved anything you entered.</Txt>
    </FormScreen>
  );
}
