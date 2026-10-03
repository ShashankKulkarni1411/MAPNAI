// P5 Topics: Sports and Film with the 3-step control. Saves immediately; reverts on failure.
import { useEffect, useState } from 'react';
import { View } from 'react-native';

import { api } from '@/api/endpoints';
import { invalidatePersona, useProfile, useUserId } from '@/api/hooks';
import { FormScreen } from '@/components/Screen';
import { Txt } from '@/components/Txt';
import { Segmented, TopBar } from '@/components/ui';
import { topicLevels } from '@/lib/labels';
import { useFeedback } from '@/state/feedback';

const snap = (w?: number) => (w === undefined ? 0.6 : w >= 0.8 ? 1 : w <= 0.1 ? 0 : 0.6);

export default function Topics() {
  const uid = useUserId();
  const profile = useProfile();
  const [vals, setVals] = useState({ sports: 0.6, entertainment_movies: 0.6 });
  useEffect(() => {
    if (profile.data) setVals({ sports: snap(profile.data.topics.sports), entertainment_movies: snap(profile.data.topics.entertainment_movies) });
  }, [profile.data]);

  async function change(topic: 'sports' | 'entertainment_movies', v: number) {
    const prev = vals;
    const next = { ...vals, [topic]: v };
    if (next.sports === 0 && next.entertainment_movies === 0) {
      useFeedback.getState().showToast('Pick at least one, or choose Some for both.');
      return;
    }
    setVals(next);
    try {
      await api.patchTopics(uid, { [topic]: v });
      invalidatePersona();
      useFeedback.getState().showToast('Updated. Your brief reflects this on refresh');
    } catch {
      setVals(prev);
      useFeedback.getState().showToast("Couldn't save. Try again.");
    }
  }

  const opts = topicLevels.map((l) => ({ label: l.label, value: l.value as number }));
  return (
    <FormScreen top={<TopBar title="Topics" />}>
      <View style={{ gap: 10 }}>
        <Txt v="metaBold">Sports</Txt>
        <Segmented label="Sports" value={vals.sports} onChange={(v) => change('sports', v)} options={opts} />
        <Txt v="metaBold">Film</Txt>
        <Segmented label="Film" value={vals.entertainment_movies} onChange={(v) => change('entertainment_movies', v)} options={opts} />
      </View>
      <Txt v="meta" muted>Must-know stories about what you follow appear whatever you choose here. Other news appears only when it involves what you follow.</Txt>
    </FormScreen>
  );
}
