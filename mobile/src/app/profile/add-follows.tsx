// P4 Add follows: the same component as O4.
import { router } from 'expo-router';
import { useState } from 'react';

import { errorCopy } from '@/api/client';
import { useFollow, useProfile } from '@/api/hooks';
import { Button } from '@/components/Button';
import { Connection } from '@/components/follow/ConnectionSheet';
import { defaultRoleFor, FollowPicker } from '@/components/follow/FollowPicker';
import { FormScreen } from '@/components/Screen';
import { Txt } from '@/components/Txt';
import { InlineError, TopBar } from '@/components/ui';
import { importance } from '@/lib/labels';
import { useFeedback } from '@/state/feedback';
import { useSession } from '@/state/session';

export default function AddFollows() {
  const ctx = useSession((s) => s.context);
  const liked = useSession((s) => s.swipes.likedEntities);
  const profile = useProfile();
  const follow = useFollow();
  const [tray, setTray] = useState<Connection[]>([]);
  const followed = new Set(profile.data?.exposures.map((e) => e.key));

  const save = () =>
    follow.mutate({ upsert: tray.map(({ key, role, weight }) => ({ key, role, weight })) }, {
      onSuccess: () => {
        useFeedback.getState().showToast(tray.length === 1 ? `Following ${tray[0].name} · ${importance[tray[0].weight].label}` : `Following ${tray.length} more`);
        router.back();
      },
    });

  return (
    <FormScreen top={<TopBar title="Add follows" />}
      footer={<Button label={tray.length ? `Follow ${tray.length}` : 'Follow'} disabled={!tray.length} loading={follow.isPending} onPress={save} />}>
      <Txt v="body" muted>Follows decide what becomes must-know for you, and what can alert you.</Txt>
      <FollowPicker tray={tray} setTray={setTray} defaultRole={defaultRoleFor(ctx)}
        suggestions={[{ title: 'From stories you liked', items: liked.filter((e) => !followed.has(e.key)) }]} />
      {follow.isError && <InlineError text={errorCopy(follow.error, "Couldn't save your follows. Try again.")} />}
    </FormScreen>
  );
}
