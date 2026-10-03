// One toast at a time, above the tab bar, announced politely to screen readers (spec §30, §31).
import { useEffect } from 'react';
import { AccessibilityInfo, Pressable, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { useFeedback } from '@/state/feedback';
import { radius, space } from '@/theme/tokens';
import { useTheme } from '@/theme/useTheme';
import { Txt } from './Txt';

export function ToastHost() {
  const toast = useFeedback((s) => s.toast);
  const dismiss = useFeedback((s) => s.dismissToast);
  const { c } = useTheme();
  const insets = useSafeAreaInsets();

  useEffect(() => {
    if (!toast) return;
    AccessibilityInfo.announceForAccessibility(toast.undo ? `${toast.message}. Undo available.` : toast.message);
    const t = setTimeout(dismiss, 5000);
    return () => clearTimeout(t);
  }, [toast, dismiss]);

  if (!toast) return null;
  return (
    <View pointerEvents="box-none" style={{ position: 'absolute', left: 0, right: 0, bottom: insets.bottom + 84, alignItems: 'center' }}>
      <View accessibilityLiveRegion="polite" style={{ flexDirection: 'row', alignItems: 'center', gap: 16, backgroundColor: c.ink, borderRadius: radius.button, paddingLeft: space.lg, paddingRight: space.sm, minHeight: 48, marginHorizontal: space.gutter, maxWidth: 520 }}>
        <Txt v="meta" color={c.bg} style={{ flexShrink: 1 }}>{toast.message}</Txt>
        {toast.undo && (
          <Pressable accessibilityRole="button" accessibilityLabel="Undo" hitSlop={8}
            onPress={() => { toast.undo?.(); dismiss(); }}
            style={{ minHeight: 44, justifyContent: 'center', paddingHorizontal: 8 }}>
            <Txt v="metaBold" color={c.highlight}>Undo</Txt>
          </Pressable>
        )}
      </View>
    </View>
  );
}
