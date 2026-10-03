import { ReactNode } from 'react';
import { View } from 'react-native';

import { space } from '@/theme/tokens';
import { Txt } from './Txt';
import { Progress } from './ui';

export function OnboardingTop({ step, right }: { step: number; right?: ReactNode }) {
  return (
    <View style={{ paddingHorizontal: space.gutter, paddingTop: space.md, gap: space.sm }}>
      <View style={{ flexDirection: 'row', alignItems: 'center', minHeight: 44 }}>
        <Txt v="meta" muted style={{ flex: 1 }} tabular>{`${step} of 6`}</Txt>
        {right}
      </View>
      <Progress step={step} total={6} />
    </View>
  );
}
