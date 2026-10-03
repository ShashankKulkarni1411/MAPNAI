import { Text, TextProps } from 'react-native';

import { type as typeScale, TypeVariant } from '@/theme/tokens';
import { useTheme } from '@/theme/useTheme';

type Props = TextProps & { v?: TypeVariant; color?: string; muted?: boolean; tabular?: boolean };

export function Txt({ v = 'body', color, muted, tabular, style, ...rest }: Props) {
  const { c } = useTheme();
  return (
    <Text
      {...rest}
      style={[
        typeScale[v],
        { color: color ?? (muted ? c.ink2 : c.ink) },
        tabular && { fontVariant: ['tabular-nums'] },
        style,
      ]}
    />
  );
}
