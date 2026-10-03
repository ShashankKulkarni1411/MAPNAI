// Launch gate: signed out → A1, unverified → A4, onboarding unfinished → resume at the first incomplete step.
import { Redirect } from 'expo-router';

import { onboardingRoute, useSession } from '@/state/session';

export default function Index() {
  const { accessToken, emailVerified, onboarding } = useSession();
  if (!accessToken) return <Redirect href="/(auth)/welcome" />;
  if (!emailVerified) return <Redirect href="/(auth)/verify" />;
  return <Redirect href={onboardingRoute(onboarding) as never} />;
}
