// T7 Help and feedback. The support inbox is Proposed; until then, email.
import { Linking, View } from 'react-native';

import { Button } from '@/components/Button';
import { FormScreen } from '@/components/Screen';
import { Txt } from '@/components/Txt';
import { SectionTitle, TopBar } from '@/components/ui';

// TODO: set the team support address before release
const SUPPORT_EMAIL = 'support@example.com';

const FAQ: [string, string][] = [
  ['Why is a story must-know?', 'It’s big news about something you follow. Tap the why line on any card to see the connection.'],
  ['Why don’t I get alerts?', 'Alerts need an Essential or Important follow and a big story. Most days there are none, and that’s by design.'],
  ['What does “Limited analysis” mean?', 'MAPNAI analyses sports and film in depth. Other news shows a snippet only.'],
];

export default function Help() {
  return (
    <FormScreen top={<TopBar title="Help and feedback" />}>
      {FAQ.map(([q, a]) => (
        <View key={q} style={{ gap: 4 }}>
          <Txt v="metaBold">{q}</Txt>
          <Txt v="body" muted>{a}</Txt>
        </View>
      ))}
      <SectionTitle title="Report a problem" />
      <Button label="Email the team" variant="secondary" onPress={() => void Linking.openURL(`mailto:${SUPPORT_EMAIL}?subject=MAPNAI%20feedback`)} />
    </FormScreen>
  );
}
