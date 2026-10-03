// T4 Account (basic). Name/email/password changes need the Proposed auth endpoints.
import { FormScreen } from '@/components/Screen';
import { Txt } from '@/components/Txt';
import { Row, TopBar } from '@/components/ui';
import { useSession } from '@/state/session';

export default function Account() {
  const { name, email } = useSession();
  return (
    <FormScreen top={<TopBar title="Account" />}>
      <Row title="Name" sub={name ?? ''} />
      <Row title="Email" sub={email ?? ''} />
      <Txt v="meta" muted>Changing your email or password, signing out of all devices and deleting your account arrive with account services in a later update.</Txt>
    </FormScreen>
  );
}
