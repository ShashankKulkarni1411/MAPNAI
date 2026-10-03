import { ActivityIndicator, Pressable, PressableProps, StyleProp, View, ViewStyle } from 'react-native';

import { radius } from '@/theme/tokens';
import { useTheme } from '@/theme/useTheme';
import { Glyph, GlyphName } from './Glyph';
import { Txt } from './Txt';

type Variant = 'primary' | 'secondary' | 'text' | 'destructive' | 'highlight';

type Props = Omit<PressableProps, 'style'> & {
  label: string;
  variant?: Variant;
  loading?: boolean;
  icon?: GlyphName;
  small?: boolean;
  style?: StyleProp<ViewStyle>;
  forceDark?: boolean;
};

// Labels are verbs; no trailing arrows (spec §30)
export function Button({ label, variant = 'primary', loading, icon, small, style, disabled, forceDark, ...rest }: Props) {
  const { c } = useTheme({ forceDark });
  const bg =
    variant === 'primary' ? c.ink : variant === 'highlight' ? c.highlight : variant === 'secondary' ? 'transparent' : 'transparent';
  const fg =
    variant === 'primary' ? c.bg : variant === 'highlight' ? c.onHighlight : variant === 'destructive' ? c.impact : c.ink;
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ disabled: !!disabled || loading, busy: loading }}
      disabled={disabled || loading}
      hitSlop={6}
      {...rest}
      style={({ pressed }) => [
        {
          minHeight: small ? 36 : 48,
          paddingHorizontal: variant === 'text' ? 4 : small ? 14 : 20,
          borderRadius: radius.button,
          backgroundColor: bg,
          borderWidth: variant === 'secondary' ? 1.5 : 0,
          borderColor: c.hairline,
          alignItems: 'center',
          justifyContent: 'center',
          opacity: disabled ? 0.45 : pressed ? 0.75 : 1,
        },
        style,
      ]}
    >
      {loading ? (
        <ActivityIndicator color={fg} />
      ) : (
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
          {icon && <Glyph name={icon} color={fg} size={18} />}
          <Txt v="button" color={fg} style={small ? { fontSize: 14 } : undefined}>
            {label}
          </Txt>
        </View>
      )}
    </Pressable>
  );
}
