// O3 Swipe ten headlines. Judgements stay on the device and are posted after O4, so a like adds to a follow's prior.
import { useQuery } from '@tanstack/react-query';
import { router } from 'expo-router';
import { useEffect, useState } from 'react';

import { api } from '@/api/endpoints';
import type { Headline } from '@/api/types';
import { Button } from '@/components/Button';
import { OnboardingTop } from '@/components/OnboardingTop';
import { FormScreen } from '@/components/Screen';
import { SwipeDeck, Judgement } from '@/components/SwipeDeck';
import { Txt } from '@/components/Txt';
import { CardSkeleton } from '@/components/ui';
import { useSession } from '@/state/session';

export default function Swipe() {
  const s = useSession();
  const q = useQuery({ queryKey: ['onboarding-headlines'], queryFn: api.headlines, retry: 1 });
  const [verdicts, setVerdicts] = useState<Record<string, { j: Judgement; h: Headline }>>({});
  const [done, setDone] = useState(false);

  function finish() {
    const vs = Object.values(verdicts);
    const liked = vs.filter((v) => v.j === 'like');
    const ents = new Map<string, { key: string; name: string }>();
    liked.forEach((v) => v.h.entities?.forEach((e) => ents.set(e.key, e)));
    s.set({
      swipes: {
        likes: liked.map((v) => v.h.article_id),
        dislikes: vs.filter((v) => v.j === 'dislike').map((v) => v.h.article_id),
        likedEntities: [...ents.values()].slice(0, 8),
      },
    });
    s.advance('follow');
    router.push('/onboarding/follow');
  }

  // Zero headlines or an error: skip O3 with a one-line note
  const empty = q.isError || (q.isSuccess && q.data.length === 0);
  useEffect(() => {
    if (empty) {
      const t = setTimeout(finish, 1500);
      return () => clearTimeout(t);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [empty]);

  return (
    <FormScreen
      top={<OnboardingTop step={3} right={<Button label="Skip all" variant="text" small onPress={finish} />} />}
      footer={done ? <Button label="Continue" onPress={finish} /> : undefined}
    >
      <Txt v="screenTitle" accessibilityRole="header">Which of these would you read?</Txt>
      <Txt v="body" muted>Swipe right for more like this, left for less.</Txt>
      {q.isLoading && <CardSkeleton />}
      {empty && <Txt v="body" muted>No headlines to show right now. Moving on.</Txt>}
      {q.data && q.data.length > 0 && (
        <SwipeDeck
          items={q.data}
          onJudge={(h, j) => setVerdicts((v) => ({ ...v, [h.article_id]: { j, h } }))}
          onUndo={(h) => setVerdicts(({ [h.article_id]: _, ...rest }) => rest)}
          onDone={() => setDone(true)}
        />
      )}
    </FormScreen>
  );
}
