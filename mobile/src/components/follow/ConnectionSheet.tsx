// P3 Edit connection: role as verbs, importance with outcome copy, Stop following.
import { useEffect, useState } from 'react';
import { Alert, View } from 'react-native';

import type { Role, WeightLevel } from '@/api/types';
import { importance, roleOrder, roleTitle } from '@/lib/labels';
import { useSession } from '@/state/session';
import { Button } from '../Button';
import { Sheet } from '../Sheet';
import { Txt } from '../Txt';
import { Chip, Segmented } from '../ui';

export type Connection = { key: string; name: string; role: Role; weight: WeightLevel };

type Props = {
  value: Connection | null;
  onClose: () => void;
  onSave: (c: Connection) => void;
  onRemove?: (c: Connection) => void;
  saving?: boolean;
};

export function ConnectionSheet({ value, onClose, onSave, onRemove, saving }: Props) {
  const fanOnly = useSession((s) => s.context.length === 0 || s.context.every((x) => x === 'fan' || x === 'fantasy'));
  const [role, setRole] = useState<Role>('follows');
  const [weight, setWeight] = useState<WeightLevel>(2);
  const [expanded, setExpanded] = useState(!fanOnly);

  useEffect(() => {
    if (value) {
      setRole(value.role);
      setWeight(value.weight);
      setExpanded(!fanOnly || value.role !== 'follows');
    }
  }, [value, fanOnly]);

  const roles = expanded ? roleOrder : (['follows'] as Role[]);

  return (
    <Sheet visible={!!value} onClose={onClose} title={value?.name}>
      <Txt v="metaBold">How you’re connected</Txt>
      <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8 }}>
        {roles.map((r) => (
          <Chip key={r} label={roleTitle[r]} selected={role === r} onPress={() => setRole(r)} />
        ))}
      </View>
      {!expanded && <Button label="Other ways you’re connected" variant="text" small onPress={() => setExpanded(true)} style={{ alignSelf: 'flex-start' }} />}
      <Txt v="metaBold">How important is it to you?</Txt>
      <Segmented<WeightLevel>
        label="Importance"
        value={weight}
        onChange={setWeight}
        options={[3, 2, 1].map((w) => ({ label: importance[w as WeightLevel].label, value: w as WeightLevel }))}
      />
      <Txt v="body" muted accessibilityLiveRegion="polite">{importance[weight].outcome}</Txt>
      {value && <Button label="Save" loading={saving} onPress={() => onSave({ ...value, role, weight })} />}
      {value && onRemove && (
        <Button label="Stop following" variant="destructive" onPress={() => {
          if (value.weight !== 3) return onRemove(value);
          Alert.alert(`Stop following ${value.name}?`, 'Its must-know stories and alerts will stop.', [
            { text: 'Cancel', style: 'cancel' },
            { text: 'Stop following', style: 'destructive', onPress: () => onRemove(value) },
          ]);
        }} />
      )}
    </Sheet>
  );
}
