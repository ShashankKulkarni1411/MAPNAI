// A1 Welcome: the product's value at a glance, with a static sample Must know card.
import { router } from 'expo-router';
import { View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { Button } from '@/components/Button';
import { SignalBars } from '@/components/Glyph';
import { Txt } from '@/components/Txt';
import { Pill } from '@/components/ui';
import { dark, radius, space } from '@/theme/tokens';

export default function Welcome() {
  const insets = useSafeAreaInsets();
  const c = dark; // the welcome screen is always night-navy
  return (
    <View style={{ flex: 1, backgroundColor: c.bg, paddingTop: insets.top + space.xxl, paddingBottom: insets.bottom + space.lg, paddingHorizontal: space.gutter, justifyContent: 'space-between' }}>
      <View style={{ gap: space.lg, maxWidth: 560, alignSelf: 'center', width: '100%' }}>
        <Txt v="screenTitle" color={c.ink} style={{ fontSize: 40, lineHeight: 44 }} accessibilityRole="header">MAPNAI</Txt>
        <Txt v="heroHeadline" color={c.ink}>Know what matters in sports and film, and why.</Txt>
        <View accessibilityLabel="Example: a must-know story about Virat Kohli, shown because you follow him"
          style={{ marginTop: space.xl, backgroundColor: c.surface, borderRadius: radius.card, padding: space.lg, paddingLeft: space.lg + 4, gap: 8, overflow: 'hidden' }}>
          <View style={{ position: 'absolute', left: 0, top: 0, bottom: 0, width: 4, backgroundColor: c.highlight }} />
          <View style={{ flexDirection: 'row', gap: 8 }}>
            <Pill label="Must know" kind="must" forceDark />
            <Pill label="Major" kind="impactFilled" forceDark />
          </View>
          <Txt v="cardHeadline" color={c.ink}>Kohli ruled out of first Test with hamstring strain</Txt>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
            <Txt v="why" color={c.ink}>You follow</Txt>
            <View style={{ backgroundColor: c.highlight, paddingHorizontal: 5, borderRadius: 3 }}>
              <Txt v="why" color={c.onHighlight}>Virat Kohli</Txt>
            </View>
            <SignalBars level={3} color={c.ink} dim={c.hairline} />
          </View>
          <Txt v="meta" color={c.ink2}>BBC Sport · 9 sources</Txt>
        </View>
      </View>
      <View style={{ gap: space.sm, maxWidth: 560, alignSelf: 'center', width: '100%' }}>
        <Button label="Get started" variant="highlight" onPress={() => router.push('/(auth)/create')} />
        <Button label="I have an account" variant="text" forceDark onPress={() => router.push('/(auth)/sign-in')} />
      </View>
    </View>
  );
}
