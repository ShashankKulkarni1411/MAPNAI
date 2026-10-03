import { ReactNode } from 'react';
import { KeyboardAvoidingView, Platform, ScrollView, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { space } from '@/theme/tokens';
import { useTheme } from '@/theme/useTheme';

// Form-style screen: safe area, keyboard avoidance, scrolling body, pinned footer for the primary action.
export function FormScreen({ children, footer, top }: { children: ReactNode; footer?: ReactNode; top?: ReactNode }) {
  const { c } = useTheme();
  const insets = useSafeAreaInsets();
  return (
    <KeyboardAvoidingView style={{ flex: 1, backgroundColor: c.bg }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <View style={{ paddingTop: insets.top }}>{top}</View>
      <ScrollView keyboardShouldPersistTaps="handled"
        contentContainerStyle={{ padding: space.gutter, paddingTop: space.xl, gap: space.lg, maxWidth: 560, width: '100%', alignSelf: 'center' }}>
        {children}
      </ScrollView>
      {footer && (
        <View style={{ padding: space.gutter, paddingBottom: insets.bottom + space.md, gap: space.sm, borderTopWidth: 1, borderTopColor: c.hairline, maxWidth: 560, width: '100%', alignSelf: 'center' }}>
          {footer}
        </View>
      )}
    </KeyboardAvoidingView>
  );
}
