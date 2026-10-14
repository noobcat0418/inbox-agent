import pytest

from agent.labels import LABEL_FOR, Labeler


class Call:
    def __init__(self, result):
        self.result = result

    def execute(self):
        return self.result


class FakeGmail:
    """Just enough of service.users().labels()/messages() to record what Labeler does."""

    def __init__(self, label_ids=None, counts=None):
        self.label_ids = dict(label_ids or {"INBOX": "INBOX", "UNREAD": "UNREAD"})
        self.counts = counts or {}
        self.created, self.deleted, self.modified = [], [], []

    def users(self):
        return self

    def labels(self):
        return self

    def messages(self):
        return self

    def list(self, userId):
        return Call({"labels": [{"name": n, "id": i} for n, i in self.label_ids.items()]})

    def create(self, userId, body):
        new_id = f"L{len(self.label_ids)}"
        self.label_ids[body["name"]] = new_id
        self.created.append(body["name"])
        return Call({"id": new_id})

    def get(self, userId, id):
        return Call({"id": id, "messagesTotal": self.counts.get(id, 0)})

    def delete(self, userId, id):
        self.deleted.append(id)
        self.label_ids = {n: i for n, i in self.label_ids.items() if i != id}
        return Call({})

    def modify(self, userId, id, body):
        self.modified.append((id, body))
        return Call({})


def test_creates_parent_first_and_only_once():
    g = FakeGmail()
    lab = Labeler(g)
    lab.ensure()
    lab.ensure()
    assert g.created == ["AI", *LABEL_FOR.values()]


def test_apply_adds_one_ai_label_and_never_touches_inbox_or_unread():
    g = FakeGmail()
    assert Labeler(g).apply("m1", "important") == "AI/Important"
    (msg_id, body), = g.modified
    ids = g.label_ids
    assert msg_id == "m1"
    assert body["addLabelIds"] == [ids["AI/Important"]]
    assert set(body["removeLabelIds"]) == {ids["AI/To-do"], ids["AI/FYI"], ids["AI/Noise"]}
    assert not {"INBOX", "UNREAD", "TRASH", "STARRED"} & set(body["addLabelIds"] + body["removeLabelIds"])


def test_unclassified_email_is_left_alone():
    g = FakeGmail()
    assert Labeler(g).apply("m1", "unclassified") is None
    assert g.modified == []


def test_guard_refuses_labels_outside_ai():
    lab = Labeler(FakeGmail())
    with pytest.raises(ValueError, match="outside AI/"):
        lab._modify("m1", add=[], remove=["INBOX"])


def test_unlabel_deletes_only_ai_labels():
    g = FakeGmail()
    lab = Labeler(g)
    lab.ensure()
    g.label_ids["Work"] = "W1"
    deleted = lab.remove_all()
    assert set(deleted) == {"AI", *LABEL_FOR.values()}
    assert "Work" in g.label_ids and "INBOX" in g.label_ids


def test_unlabel_keeps_parent_holding_own_labels():
    g = FakeGmail()
    lab = Labeler(g)
    lab.ensure()
    g.label_ids["AI/Mine"] = "M1"
    assert "AI" not in lab.remove_all()
    assert "AI" in g.label_ids
