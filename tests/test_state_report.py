from agent.classify import UNCLASSIFIED, Result, Todo
from agent.report import render_summary, render_todos
from agent.state import State


def email(i, subject="Subject"):
    return {"id": f"m{i}", "received_at": 1760400000 + i, "from": f"Sender {i} <s{i}@x.com>",
            "subject": subject, "snippet": "", "labels": [], "body": ""}


def test_unclassified_is_retried_not_marked_done(tmp_path):
    st = State(tmp_path / "t.db")
    st.save(email(1), Result("fyi", summary="ok"), "model")
    st.save(email(2), Result(UNCLASSIFIED, error="boom"), "model")
    assert st.done_ids() == {"m1"} and st.retry_ids() == ["m2"]

    st.save(email(2), Result("noise"), "model")  # the retry succeeded
    assert st.done_ids() == {"m1", "m2"} and st.retry_ids() == []


def test_todos_dedupe_sort_and_close(tmp_path):
    st = State(tmp_path / "t.db")
    result = Result("todo", todos=[Todo("Call mom"), Todo("Pay bill", "2026-10-17")])
    st.save(email(1), result, "model")
    st.save(email(1), result, "model")  # reprocessing must not duplicate to-dos

    rows = st.open_todos()
    assert [r["task"] for r in rows] == ["Pay bill", "Call mom"]  # dated first
    assert st.mark_done([rows[0]["id"]]) == 1
    assert [r["task"] for r in st.open_todos()] == ["Call mom"]


def test_meta_round_trip(tmp_path):
    st = State(tmp_path / "t.db")
    assert st.get("last_run_at") is None
    st.set("last_run_at", "123")
    assert st.get("last_run_at") == "123"


def test_summary_puts_important_first_and_lists_errors():
    items = [
        (email(1, "Newsletter"), Result("noise")),
        (email(2, "Bill due"), Result("important", why="due soon", summary="Pay $40",
                                      todos=[Todo("Pay bill", "2026-10-17")])),
        (email(3, "Broken"), Result(UNCLASSIFIED, error="ValueError: x")),
    ]
    md = render_summary(items, run_label="2026-10-14 07:00", mode="test", model="qwen2.5:3b", skipped=4)
    assert md.index("## Important") < md.index("## To-dos") < md.index("## Noise") < md.index("## Errors")
    assert "| 1 | 0 | 0 | 1 | 1 |" in md
    assert "**Classified by:** qwen2.5:3b" in md
    assert "Pay bill (due 2026-10-17)" in md


def test_summary_admits_when_nothing_was_classified():
    md = render_summary([(email(1), Result(UNCLASSIFIED, error="down"))],
                        run_label="x", mode="t", model="qwen", skipped=0)
    assert "nothing (every email failed" in md


def test_empty_todo_list():
    assert "Nothing open" in render_todos([])
