import { forwardRef, useState } from 'react';
import { Pressable, TextInput, TextInputProps, View } from 'react-native';

import { fonts, radius } from '@/theme/tokens';
import { useTheme } from '@/theme/useTheme';
import { Txt } from './Txt';

type Props = TextInputProps & { label: string; error?: string | null; hint?: string; secureToggle?: boolean };

export const Field = forwardRef<TextInput, Props>(function Field({ label, error, hint, secureToggle, style, ...rest }, ref) {
  const { c } = useTheme();
  const [hidden, setHidden] = useState(!!secureToggle);
  return (
    <View style={{ gap: 6 }}>
      <Txt v="metaBold">{label}</Txt>
      <View style={{ flexDirection: 'row', alignItems: 'center', borderWidth: 1.5, borderColor: error ? c.impact : c.hairline, borderRadius: radius.button, backgroundColor: c.surface }}>
        <TextInput
          ref={ref}
          accessibilityLabel={label}
          placeholderTextColor={c.ink2}
          secureTextEntry={secureToggle ? hidden : rest.secureTextEntry}
          {...rest}
          style={[{ flex: 1, minHeight: 48, paddingHorizontal: 14, color: c.ink, fontFamily: fonts.body400, fontSize: 16 }, style]}
        />
        {secureToggle && (
          <Pressable onPress={() => setHidden((h) => !h)} accessibilityRole="button" accessibilityLabel={hidden ? 'Show password' : 'Hide password'} hitSlop={8} style={{ paddingHorizontal: 14, minHeight: 44, justifyContent: 'center' }}>
            <Txt v="metaBold" muted>{hidden ? 'Show' : 'Hide'}</Txt>
          </Pressable>
        )}
      </View>
      {error ? <Txt v="meta" color={c.impact} accessibilityLiveRegion="polite">{error}</Txt> : hint ? <Txt v="meta" muted>{hint}</Txt> : null}
    </View>
  );
});
