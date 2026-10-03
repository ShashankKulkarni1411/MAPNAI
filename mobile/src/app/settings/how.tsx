// T6 How MAPNAI works: five short cards, each linking to the control that changes it.
import { router } from 'expo-router';
import { View } from 'react-native';

import { Button } from '@/components/Button';
import { FormScreen } from '@/components/Screen';
import { Txt } from '@/components/Txt';
import { TopBar } from '@/components/ui';
import { radius, space } from '@/theme/tokens';
import { useTheme } from '@/theme/useTheme';

const CARDS = [
  { title: 'Must know', body: 'A story is must-know when it’s big and it’s about something you follow. How strongly you follow it decides how big it has to be. Reading habits never make a story must-know.', link: 'Your connections', to: '/profile/knows' },
  { title: 'One card per event', body: 'When many outlets cover the same event, you see one card with the number of sources and another angle, not ten copies.', link: null, to: null },
  { title: 'Every story says why', body: 'Each card has one line explaining why it’s here. Tap it to see more and to change it.', link: null, to: null },
  { title: 'Alerts', body: 'Alerts are only for big news about what’s Essential or Important to you: at most a few a day, one per story, never during quiet hours.', link: 'Alert settings', to: '/settings/notifications' },
  { title: 'What MAPNAI learns', body: 'More, Less, opening and reading time shape your For you picks. MAPNAI never changes your follows on its own; it suggests, and you decide.', link: 'What MAPNAI knows', to: '/profile/knows' },
] as const;

export default function How() {
  const { c } = useTheme();
  return (
    <FormScreen top={<TopBar title="How MAPNAI works" />}>
      {CARDS.map((card) => (
        <View key={card.title} style={{ backgroundColor: c.surface, borderRadius: radius.card, borderWidth: 1, borderColor: c.hairline, padding: space.lg, gap: 6 }}>
          <Txt v="cardHeadline">{card.title}</Txt>
          <Txt v="body" muted>{card.body}</Txt>
          {card.link && <Button label={card.link} variant="text" small style={{ alignSelf: 'flex-start' }} onPress={() => router.push(card.to as never)} />}
        </View>
      ))}
    </FormScreen>
  );
}
