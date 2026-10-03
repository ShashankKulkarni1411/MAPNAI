// Bottom sheet on a transparent Modal: drag-to-close is replaced by a visible Close button and a scrim tap,
// which also satisfies the gesture-alternative rule (spec §31). Modal traps screen-reader focus.
import { ReactNode } from 'react';
import { Modal, Pressable, ScrollView, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { radius, space } from '@/theme/tokens';
import { useTheme } from '@/theme/useTheme';
import { IconButton } from './ui';
import { Txt } from './Txt';

export function Sheet({ visible, onClose, title, children }: { visible: boolean; onClose: () => void; title?: string; children: ReactNode }) {
  const { c } = useTheme();
  const insets = useSafeAreaInsets();
  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose} statusBarTranslucent>
      <Pressable style={{ flex: 1, backgroundColor: c.scrim }} onPress={onClose} accessibilityLabel="Close" accessibilityRole="button" />
      <View style={{ backgroundColor: c.bg, borderTopLeftRadius: radius.sheet, borderTopRightRadius: radius.sheet, maxHeight: '85%', paddingBottom: insets.bottom + space.md }}>
        <View style={{ alignItems: 'center', paddingTop: 8 }}>
          <View style={{ width: 36, height: 4, borderRadius: 2, backgroundColor: c.hairline }} />
        </View>
        <View style={{ flexDirection: 'row', alignItems: 'center', paddingLeft: space.gutter, paddingRight: space.sm }}>
          <Txt v="sectionTitle" accessibilityRole="header" style={{ flex: 1 }}>{title}</Txt>
          <IconButton icon="close" label="Close" onPress={onClose} />
        </View>
        <ScrollView contentContainerStyle={{ paddingHorizontal: space.gutter, paddingBottom: space.lg, gap: space.md }}>{children}</ScrollView>
      </View>
    </Modal>
  );
}
