"""The only module that writes to Gmail.

It adds and removes labels under "AI/" and nothing else: no archiving, no marking read, no trash,
no sending. gmail.modify would allow more, so _modify refuses any label id it doesn't manage.
"""
PARENT = "AI"
LABEL_FOR = {"important": "AI/Important", "todo": "AI/To-do", "fyi": "AI/FYI", "noise": "AI/Noise"}
MANAGED = (PARENT, *LABEL_FOR.values())  # parent first, so Gmail nests the others under it


class Labeler:
    def __init__(self, service):
        self.labels = service.users().labels()
        self.messages = service.users().messages()
        self._ids: dict[str, str] | None = None

    def _existing(self) -> dict[str, str]:
        resp = self.labels.list(userId="me").execute()
        return {lab["name"]: lab["id"] for lab in resp.get("labels", [])}

    def ensure(self) -> dict[str, str]:
        """Create any missing AI labels once per run. Returns name -> id."""
        if self._ids is None:
            existing = self._existing()
            for name in MANAGED:
                if name not in existing:
                    body = {"name": name, "labelListVisibility": "labelShow", "messageListVisibility": "show"}
                    existing[name] = self.labels.create(userId="me", body=body).execute()["id"]
            self._ids = {name: existing[name] for name in MANAGED}
        return self._ids

    def apply(self, msg_id: str, category: str) -> str | None:
        """Give the message its category label, replacing any other AI label. Returns the label name."""
        name = LABEL_FOR.get(category)
        if name is None:  # unclassified: leave the email alone
            return None
        ids = self.ensure()
        others = [ids[n] for n in LABEL_FOR.values() if n != name]
        self._modify(msg_id, add=[ids[name]], remove=others)
        return name

    def _modify(self, msg_id: str, add: list[str], remove: list[str]) -> None:
        allowed = {self.ensure()[n] for n in LABEL_FOR.values()}
        if not set(add) | set(remove) <= allowed:
            raise ValueError("refusing to change a label outside AI/")
        self.messages.modify(
            userId="me", id=msg_id, body={"addLabelIds": add, "removeLabelIds": remove}
        ).execute()

    def remove_all(self) -> list[str]:
        """Full undo. Deleting a label removes it from every email; the emails themselves are untouched."""
        existing = self._existing()
        deleted = []
        for name in LABEL_FOR.values():
            if name in existing:
                self.labels.delete(userId="me", id=existing[name]).execute()
                deleted.append(name)
        # Delete the parent only if it is now empty and holds none of Mike's own labels.
        own_children = [n for n in existing if n.startswith(PARENT + "/") and n not in LABEL_FOR.values()]
        if PARENT in existing and not own_children:
            info = self.labels.get(userId="me", id=existing[PARENT]).execute()
            if not info.get("messagesTotal"):
                self.labels.delete(userId="me", id=existing[PARENT]).execute()
                deleted.append(PARENT)
        self._ids = None
        return deleted
