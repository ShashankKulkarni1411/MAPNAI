// P6 Reading style with a fixed sample per combination (no LLM call to preview).
import { useEffect, useState } from 'react';
import { View } from 'react-native';

import { api } from '@/api/endpoints';
import { invalidatePersona, useProfile, useUserId } from '@/api/hooks';
import type { Style } from '@/api/types';
import { FormScreen } from '@/components/Screen';
import { Txt } from '@/components/Txt';
import { Segmented, TopBar } from '@/components/ui';
import { useFeedback } from '@/state/feedback';
import { radius, space } from '@/theme/tokens';
import { useTheme } from '@/theme/useTheme';

const SAMPLES: Record<string, string> = {
  'plain|short|low': 'Kohli will miss the first Test with a hamstring strain. He should be back for the second.',
  'plain|short|high': 'Kohli is out of the first Test with a grade-2 hamstring strain; he’s expected back for Adelaide.',
  'plain|medium|low': 'Virat Kohli will miss the first Test after scans showed a hamstring strain. The team expects him back for the second Test in Adelaide, and Shubman Gill will likely bat higher.',
  'plain|medium|high': 'Virat Kohli misses the first Test with a grade-2 hamstring strain. He’s targeting the Adelaide Test, with Gill likely promoted to No. 3.',
  'analyst|short|low': 'Losing Kohli weakens India’s middle order for the opener; his return for the second Test limits the damage.',
  'analyst|short|high': 'Kohli’s absence thins India’s top four for the opener; expect Gill at 3 and a reshuffled middle order.',
  'analyst|medium|low': 'Kohli’s injury takes India’s most experienced batter out of the opener. If he returns for the second Test as expected, the series impact is limited, but the first match now leans on a less settled order.',
  'analyst|medium|high': 'Without Kohli, India lose their anchor at 4 for the opener. Gill moving to 3 exposes the middle order to the new ball; a return for Adelaide caps the downside.',
};

export default function ReadingStyle() {
  const { c } = useTheme();
  const uid = useUserId();
  const profile = useProfile();
  const [style, setStyle] = useState<Style>({ tone: 'plain', length: 'short', jargon: 'low' });
  useEffect(() => { if (profile.data) setStyle(profile.data.style); }, [profile.data]);

  async function change(p: Partial<Style>) {
    const prev = style;
    setStyle({ ...style, ...p });
    try {
      await api.patchStyle(uid, p);
      invalidatePersona();
    } catch {
      setStyle(prev);
      useFeedback.getState().showToast("Couldn't save. Try again.");
    }
  }

  return (
    <FormScreen top={<TopBar title="Reading style" />}>
      <Txt v="metaBold">Tone</Txt>
      <Segmented label="Tone" value={style.tone} onChange={(tone) => change({ tone })} options={[{ label: 'Plain', value: 'plain' }, { label: 'Analyst', value: 'analyst' }]} />
      <Txt v="metaBold">Length</Txt>
      <Segmented label="Length" value={style.length} onChange={(length) => change({ length })} options={[{ label: 'Short', value: 'short' }, { label: 'Medium', value: 'medium' }]} />
      <Txt v="metaBold">Jargon</Txt>
      <Segmented label="Jargon" value={style.jargon} onChange={(jargon) => change({ jargon })} options={[{ label: 'Less', value: 'low' }, { label: 'More', value: 'high' }]} />
      <View style={{ backgroundColor: c.surface, borderRadius: radius.card, borderWidth: 1, borderColor: c.hairline, padding: space.lg, gap: 6 }}>
        <Txt v="label" muted>Preview</Txt>
        <Txt v="summary">{SAMPLES[`${style.tone}|${style.length}|${style.jargon}`]}</Txt>
      </View>
      <Txt v="meta" muted>Style applies when personalized summaries are on. Otherwise you see the key sentences from each article.</Txt>
    </FormScreen>
  );
}
