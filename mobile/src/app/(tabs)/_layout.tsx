// Four tabs plus a raised Ask button (spec §5). Ask opens a modal over the current tab, not a destination.
// Tapping the active tab scrolls to top (handled by each screen via useScrollToTop).
import { Tabs, router } from 'expo-router';
import type { ComponentProps } from 'react';
import { Pressable, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { Glyph, GlyphName } from '@/components/Glyph';
import { Txt } from '@/components/Txt';
import { usePrefs } from '@/state/prefs';
import { useTheme } from '@/theme/useTheme';

type BottomTabBarProps = Parameters<NonNullable<ComponentProps<typeof Tabs>['tabBar']>>[0];

const TABS: { name: string; label: string; icon: GlyphName }[] = [
  { name: 'index', label: 'Home', icon: 'home' },
  { name: 'flash', label: 'Flash', icon: 'flash' },
  { name: 'insights', label: 'Insights', icon: 'insights' },
  { name: 'profile', label: 'Profile', icon: 'profile' },
];

function TabBar({ state, navigation }: BottomTabBarProps) {
  const insets = useSafeAreaInsets();
  const flashDark = usePrefs((s) => s.flashAlwaysDark);
  const onFlash = state.routes[state.index]?.name === 'flash';
  const { c } = useTheme({ forceDark: onFlash && flashDark });

  const item = (t: (typeof TABS)[number]) => {
    const idx = state.routes.findIndex((r: { name: string }) => r.name === t.name);
    const focused = state.index === idx;
    return (
      <Pressable
        key={t.name}
        accessibilityRole="tab"
        accessibilityState={{ selected: focused }}
        accessibilityLabel={t.label}
        onPress={() => {
          const e = navigation.emit({ type: 'tabPress', target: state.routes[idx].key, canPreventDefault: true });
          if (!focused && !e.defaultPrevented) navigation.navigate(state.routes[idx].name);
        }}
        style={{ flex: 1, alignItems: 'center', justifyContent: 'center', minHeight: 52, gap: 2 }}
      >
        <Glyph name={t.icon} size={22} color={focused ? c.ink : c.ink2} filled={focused && (t.icon === 'home' || t.icon === 'profile')} />
        <Txt v="label" color={focused ? c.ink : c.ink2}>{t.label}</Txt>
      </Pressable>
    );
  };

  return (
    <View style={{ flexDirection: 'row', alignItems: 'flex-end', backgroundColor: c.bg, borderTopWidth: 1, borderTopColor: c.hairline, paddingBottom: insets.bottom, paddingHorizontal: 4 }}>
      {item(TABS[0])}
      {item(TABS[1])}
      <View style={{ flex: 1, alignItems: 'center' }}>
        <Pressable
          onPress={() => router.push('/ask')}
          accessibilityRole="button"
          accessibilityLabel="Ask MAPNAI"
          style={{ width: 56, height: 56, borderRadius: 28, marginTop: -18, backgroundColor: c.highlight, alignItems: 'center', justifyContent: 'center', borderWidth: 3, borderColor: c.bg }}
        >
          <Glyph name="ask" size={24} color={c.onHighlight} />
        </Pressable>
        <Txt v="label" color={c.ink2} style={{ marginBottom: 6 }}>Ask</Txt>
      </View>
      {item(TABS[2])}
      {item(TABS[3])}
    </View>
  );
}

export default function TabsLayout() {
  return (
    <Tabs screenOptions={{ headerShown: false }} tabBar={(p) => <TabBar {...p} />}>
      {TABS.map((t) => <Tabs.Screen key={t.name} name={t.name} options={{ title: t.label }} />)}
    </Tabs>
  );
}
