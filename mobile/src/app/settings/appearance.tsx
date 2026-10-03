// T5 Appearance: device-only.
import { Switch, View } from 'react-native';

import { FormScreen } from '@/components/Screen';
import { Txt } from '@/components/Txt';
import { Segmented, TopBar } from '@/components/ui';
import { ThemeChoice, usePrefs } from '@/state/prefs';

export default function Appearance() {
  const p = usePrefs();
  const toggle = (label: string, value: boolean, set: (v: boolean) => void) => (
    <View style={{ flexDirection: 'row', alignItems: 'center', minHeight: 48 }}>
      <Txt v="body" style={{ flex: 1 }}>{label}</Txt>
      <Switch value={value} onValueChange={set} accessibilityLabel={label} />
    </View>
  );
  return (
    <FormScreen top={<TopBar title="Appearance" />}>
      <Txt v="metaBold">Theme</Txt>
      <Segmented<ThemeChoice> label="Theme" value={p.theme} onChange={p.setTheme}
        options={[{ label: 'System', value: 'system' }, { label: 'Light', value: 'light' }, { label: 'Dark', value: 'dark' }]} />
      {toggle('Flash always dark', p.flashAlwaysDark, p.setFlashAlwaysDark)}
      {toggle('Haptics', p.haptics, p.setHaptics)}
      <Txt v="meta" muted>Text size and reduce motion follow your device settings.</Txt>
    </FormScreen>
  );
}
