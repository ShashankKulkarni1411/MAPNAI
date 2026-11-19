"""
MAPNAI — tests/test_push.py
Expo push (personalization/push.py and service.push_alerts): messages, the HTTP client with a fake session, token
registration, sending delivered alerts once, stale / no-token alerts, receipts and DeviceNotRegistered.
"""

from datetime import timedelta

import pytest

from personalization import push
from personalization.service import InvalidInput, PersonalizationService
from tests.fakes import CFG, NOW, Clock, FakeMongo, FakeVectors, NamedExposures

TOKEN_A = "ExponentPushToken[aaaaaaaaaaaaaaaaaaaaaa]"
TOKEN_B = "ExponentPushToken[bbbbbbbbbbbbbbbbbbbbbb]"
TOKEN_C = "ExpoPushToken[cccccccccccccccccccccc]"


class Resp:
    def __init__(self, body, status=200):
        self.body, self.status_code, self.content = body, status, b"x"

    def json(self):
        return self.body


class Session:
    """Records posts; send → one ok ticket per message unless the token is in `gone`; receipts from `receipts`."""

    def __init__(self, gone=(), receipts=None, fail=False):
        self.gone, self.receipts, self.fail, self.posts = set(gone), receipts or {}, fail, []

    def post(self, url, json=None, headers=None, timeout=None):
        self.posts.append((url, json, headers))
        if self.fail:
            raise ConnectionError("no network")
        if url.endswith("/getReceipts"):
            return Resp({"data": {i: self.receipts[i] for i in json["ids"] if i in self.receipts}})
        data = [{"status": "error", "message": "gone", "details": {"error": "DeviceNotRegistered"}}
                if m["to"] in self.gone else {"status": "ok", "id": f"t-{m['to'][-4:-1]}-{len(self.posts)}"}
                for m in json]
        return Resp({"data": data})


class TestMessages:
    def test_valid_token(self):
        assert push.valid_token(TOKEN_A) and push.valid_token(TOKEN_C)
        assert not push.valid_token("abc") and not push.valid_token("ExponentPushToken[]")

    def test_titles_by_kind(self):
        assert push.alert_title({"kind": "breaking_global", "title": "Kohli out"}) == "Breaking: Kohli out"
        assert push.alert_title({"title": "Acme recalls widgets", "entity_name": "Acme"}) == "Acme recalls widgets"
        assert push.alert_title({"title": "Widget recall", "entity_name": "Acme"}) == "Acme: Widget recall"
        assert push.alert_title({}) == "News for you"

    def test_build_message_opens_the_story(self):
        m = push.build_message({"alert_id": "al", "article_id": "a1", "cluster_id": "c1", "kind": "breaking_for_you",
                                "title": "T" * 300, "explanation": "why"}, TOKEN_A)
        assert m["to"] == TOKEN_A and len(m["title"]) == 178 and m["body"] == "why"
        assert m["data"] == {"article_id": "a1", "alert_id": "al", "kind": "breaking_for_you", "cluster_id": "c1"}
        assert m["channelId"] == push.CHANNEL and m["priority"] == "high"


class TestClient:
    def test_batches_of_100_and_tickets_in_order(self):
        session = Session(gone={TOKEN_B})
        client = push.ExpoPushClient(CFG, session)
        msgs = [{"to": TOKEN_A}] * 150 + [{"to": TOKEN_B}]
        tickets = client.send(msgs)
        assert [len(p[1]) for p in session.posts] == [100, 51] and len(tickets) == 151
        assert push.ticket_error(tickets[0]) is None and push.ticket_error(tickets[-1]) == push.DEVICE_GONE
        assert session.posts[0][0] == CFG.push_url and "Authorization" not in session.posts[0][2]

    def test_access_token_header(self):
        session = Session()
        push.ExpoPushClient(CFG.model_copy(update={"push_access_token": "secret"}), session).send([{"to": TOKEN_A}])
        assert session.posts[0][2]["Authorization"] == "Bearer secret"

    def test_a_failed_request_gives_error_tickets(self):
        tickets = push.ExpoPushClient(CFG, Session(fail=True)).send([{"to": TOKEN_A}, {"to": TOKEN_B}])
        assert [push.ticket_error(t) for t in tickets] == ["RequestFailed", "RequestFailed"]
        assert push.ExpoPushClient(CFG, Session(fail=True)).receipts(["x"]) == {}


@pytest.fixture
def svc():
    mongo = FakeMongo()
    mongo.db.personas.insert_many([{"user_id": u, "name": u, "topics": {}, "beta": {}, "history": []}
                                   for u in ("ana", "ben", "cy")])
    session = Session(gone={TOKEN_B})
    s = PersonalizationService(mongo=mongo, exposures=NamedExposures([], {}), vectors=FakeVectors({}), cfg=CFG,
                               clock=Clock(NOW), push_client=push.ExpoPushClient(CFG, session))
    s.session = session
    return s


def alert(alert_id, user_id, deliver_after, **kw):
    return {"alert_id": alert_id, "user_id": user_id, "cluster_id": alert_id, "article_id": f"art-{alert_id}",
            "kind": "exposure", "title": "Acme recalls widgets", "explanation": "You own Acme.",
            "deliver_after": deliver_after, **kw}


class TestTokens:
    def test_register_validate_move_and_delete(self, svc):
        assert svc.register_push_token("ana", TOKEN_A, "android")["active"] is True
        with pytest.raises(InvalidInput):
            svc.register_push_token("ana", "not-a-token")
        with pytest.raises(InvalidInput):
            svc.register_push_token("ana", TOKEN_A, "symbian")
        svc.register_push_token("ben", TOKEN_A, "android")                # the phone changed hands
        assert svc.logs.push_tokens_for(["ana", "ben"]) == {"ben": [TOKEN_A]}
        assert svc.unregister_push_token("ana", TOKEN_A)["deleted"] == 0
        assert svc.unregister_push_token("ben", TOKEN_A)["deleted"] == 1


class TestPushAlerts:
    def test_send_once_per_device_and_deactivate_gone_tokens(self, svc):
        svc.register_push_token("ana", TOKEN_A, "ios")
        svc.register_push_token("ana", TOKEN_C, "android")
        svc.register_push_token("ben", TOKEN_B, "android")
        svc.mongo.db.alerts.insert_many([
            alert("a1", "ana", NOW - timedelta(minutes=2)),
            alert("b1", "ben", NOW - timedelta(minutes=1)),
            alert("c1", "cy", NOW),                                      # no device
            alert("old", "ana", NOW - timedelta(hours=7)),                # older than push_max_age_h
            alert("later", "ana", NOW + timedelta(hours=3)),              # still held by quiet hours
        ])
        out = svc.push_alerts()
        assert out == {"alerts": 2, "messages": 3, "sent": 2, "errors": 1, "stale": 1, "no_token": 1,
                       "tokens_deactivated": 1, "receipts_checked": 0}
        a1 = svc.mongo.db.alerts.find_one({"alert_id": "a1"})["push"]
        assert a1["status"] == "sent" and len(a1["tickets"]) == 2
        assert svc.mongo.db.alerts.find_one({"alert_id": "b1"})["push"]["status"] == "failed"
        assert svc.mongo.db.alerts.find_one({"alert_id": "later"}).get("push") is None
        assert svc.logs.push_tokens_for(["ben"]) == {}
        # nothing new: no request at all
        n = len(svc.session.posts)
        assert svc.push_alerts()["messages"] == 0 and len(svc.session.posts) == n

    def test_receipts_after_the_delay(self, svc):
        svc.register_push_token("ana", TOKEN_A, "ios")
        svc.register_push_token("ana", TOKEN_C, "android")
        svc.mongo.db.alerts.insert_one(alert("a1", "ana", NOW))
        svc.push_alerts()
        tickets = svc.mongo.db.alerts.find_one({"alert_id": "a1"})["push"]["tickets"]
        ids = {t["token"]: t["id"] for t in tickets}
        svc.session.receipts = {ids[TOKEN_A]: {"status": "ok"},
                                ids[TOKEN_C]: {"status": "error", "details": {"error": "DeviceNotRegistered"}}}
        svc.clock.now = NOW + timedelta(minutes=5)
        assert svc.push_alerts()["receipts_checked"] == 0                 # too early
        svc.clock.now = NOW + timedelta(minutes=16)
        out = svc.push_alerts()
        assert out["receipts_checked"] == 1 and out["tokens_deactivated"] == 1
        state = svc.mongo.db.alerts.find_one({"alert_id": "a1"})["push"]
        assert {t["token"]: t["receipt"] for t in state["tickets"]} == {TOKEN_A: "ok", TOKEN_C: "DeviceNotRegistered"}
        assert svc.logs.push_tokens_for(["ana"]) == {"ana": [TOKEN_A]}
        assert svc.push_alerts()["receipts_checked"] == 0                 # read once

    def test_run_alerts_pushes_when_enabled(self, svc):
        svc.register_push_token("ana", TOKEN_A, "ios")
        svc.mongo.db.alerts.insert_one(alert("a1", "ana", NOW))
        out = svc.run_alerts()
        assert out["push"]["sent"] == 1
        off = PersonalizationService(mongo=svc.mongo, exposures=NamedExposures([], {}), vectors=FakeVectors({}),
                                     cfg=CFG.model_copy(update={"enable_push": False}), clock=Clock(NOW))
        assert "push" not in off.run_alerts()
