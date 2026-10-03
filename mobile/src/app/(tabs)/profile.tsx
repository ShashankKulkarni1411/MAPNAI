// P1 Profile
import { router, useScrollToTop } from 'expo-router';
import { useRef } from 'react';
import { ScrollView, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { useProfile, useProposals } from '@/api/hooks';
import { Button } from '@/components/Button';
import { Txt } from '@/components/Txt';
import { InlineError, Row, SectionTitle, Skeleton } from '@/components/ui';
import { uiSentence } from '@/lib/profileWords';
import { signOutEverywhere } from '@/lib/signOut';
import { useSession } from '@/state/session';
import { radius, space } from '@/theme/tokens';
import { useTheme } from '@/theme/useTheme';

export default function Profile() {
  const { c } = useTheme();
  const insets = useSafeAreaInsets();
  const profile = useProfile();
  const proposals = useProposals();
  const { name, email } = useSession();
  const scroll = useRef<ScrollView>(null);
  useScrollToTop(scroll);
  const since = profile.data?.created_at ? new Date(profile.data.created_at).toLocaleDateString([], { month: 'short', year: 'numeric' }) : null;
  const sentences = (profile.data?.sentences ?? []).map(uiSentence).slice(0, 3);

  return (
    <ScrollView ref={scroll} style={{ backgroundColor: c.bg }}
      contentContainerStyle={{ paddingTop: insets.top + space.md, paddingHorizontal: space.gutter, paddingBottom: space.xxl * 2, maxWidth: 720, width: '100%', alignSelf: 'center' }}>
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: space.md }}>
        <View style={{ width: 56, height: 56, borderRadius: 28, backgroundColor: c.ink, alignItems: 'center', justifyContent: 'center' }}>
          <Txt v="sectionTitle" color={c.bg}>{(name ?? '?').slice(0, 1).toUpperCase()}</Txt>
        </View>
        <View style={{ flex: 1 }}>
          <Txt v="sectionTitle" accessibilityRole="header">{name}</Txt>
          <Txt v="meta" muted>{email}</Txt>
          {since && <Txt v="meta" muted>Member since {since}</Txt>}
        </View>
      </View>

      <SectionTitle title="What MAPNAI knows" />
      <View style={{ backgroundColor: c.surface, borderRadius: radius.card, borderWidth: 1, borderColor: c.hairline, padding: space.lg, gap: 8 }}>
        {profile.isLoading && (<><Skeleton h={16} /><Skeleton h={16} w="80%" /></>)}
        {profile.isError && <InlineError text="Couldn't load your profile." onRetry={() => profile.refetch()} />}
        {profile.data && sentences.length === 0 && <Txt v="body" muted>You’re not following anything yet.</Txt>}
        {sentences.map((s, i) => <Txt key={i} v="body">{s}</Txt>)}
        <Button label="See everything" variant="text" small onPress={() => router.push('/profile/knows')} style={{ alignSelf: 'flex-start' }} />
      </View>

      {!!proposals.data?.length && (
        <Row title={`${proposals.data.length} suggested change${proposals.data.length === 1 ? '' : 's'}`} onPress={() => router.push('/profile/suggestions')} />
      )}

      <SectionTitle title="Library" />
      <Row title="Saved" onPress={() => router.push('/profile/saved')} />

      <SectionTitle title="Settings" />
      <Row title="Alerts and notifications" onPress={() => router.push('/settings/notifications')} />
      <Row title="Settings" onPress={() => router.push('/settings')} />
      <Row title="How MAPNAI works" onPress={() => router.push('/settings/how')} />
      <Button label="Sign out" variant="secondary" style={{ marginTop: space.xl }} onPress={signOutEverywhere} />
    </ScrollView>
  );
}
