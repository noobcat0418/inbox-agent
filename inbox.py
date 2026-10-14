"""Personal Gmail reader: triage new mail (default) or previous mail (--backfill) with a local model.

  python inbox.py --check                    sign in to Gmail and check the model, touch nothing
  python inbox.py                            new mail since the last run (first run: last 2 days)
  python inbox.py --backfill 90d --max 200   previous mail, newest first, resumable
  python inbox.py --dry-run                  list what would be processed; no model calls, nothing saved
  python inbox.py --done 3 7                 close to-dos by id
  python inbox.py --relabel                  add AI/ labels to emails processed earlier (no model calls)
  python inbox.py --unlabel                  remove every AI/ label (full undo; emails untouched)
"""
import argparse
import sys
import time
from collections import Counter
from datetime import datetime

from agent import config, gmail
from agent.classify import UNCLASSIFIED, Result, classify, system_prompt
from agent.labels import Labeler
from agent.report import render_summary, render_todos
from agent.state import State

FIRST_RUN_DAYS = 2
OVERLAP_SECONDS = 3600  # re-scan the last hour of the window; processed ids are skipped anyway


def parse_days(value: str) -> int:
    days = value.lower().removesuffix("d")
    if not days.isdigit() or int(days) < 1:
        raise argparse.ArgumentTypeError("use a number of days, e.g. 90d")
    return int(days)


def run_check(cfg, service) -> int:
    from agent.llm import LLM

    p = gmail.profile(service)
    print(f"Gmail: signed in as {p['emailAddress']} ({p['messagesTotal']} messages)")
    try:
        warning = LLM(cfg).check()
    except Exception as e:
        print(f"Model: NOT reachable at {cfg.llm_base_url} ({type(e).__name__}). Is Ollama running?")
        return 2
    if warning:
        print(f"Model: {warning}")
        return 2
    print(f"Model: {cfg.llm_model} ready at {cfg.llm_base_url}")
    return 0


def main(argv=None) -> int:
    sys.stdout.reconfigure(errors="replace")  # emoji in subjects must not crash a Windows console
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="check Gmail sign-in and the model, then exit")
    ap.add_argument("--backfill", type=parse_days, metavar="DAYS", help="process previous mail from the last N days, e.g. 90d")
    ap.add_argument("--max", type=int, default=200, help="most emails to process this run (default 200)")
    ap.add_argument("--dry-run", action="store_true", help="list what would be processed; no model calls, nothing saved")
    ap.add_argument("--all-categories", action="store_true", help="include Gmail's Promotions and Social tabs")
    ap.add_argument("--done", type=int, nargs="+", metavar="ID", help="mark to-dos done by id")
    ap.add_argument("--no-label", action="store_true", help="don't add Gmail labels this run")
    ap.add_argument("--relabel", action="store_true", help="label emails processed earlier, then exit")
    ap.add_argument("--unlabel", action="store_true", help="remove every AI/ label, then exit")
    args = ap.parse_args(argv)

    cfg = config.load()
    cfg.out_dir.mkdir(exist_ok=True)
    state = State(cfg.db_file)
    todos_path = cfg.out_dir / "todos.md"

    if args.done:
        n = state.mark_done(args.done)
        todos_path.write_text(render_todos(state.open_todos()), encoding="utf-8")
        print(f"Marked {n} to-do(s) done. Open list: {todos_path}")
        return 0

    service = gmail.connect(cfg)
    if args.check:
        return run_check(cfg, service)
    if args.unlabel:
        deleted = Labeler(service).remove_all()
        print("Removed: " + (", ".join(deleted) if deleted else "no AI labels found") + ". Emails are untouched.")
        return 0
    if args.relabel:
        labeler, n = Labeler(service), 0
        for row in state.classified():
            try:
                labeler.apply(row["id"], row["category"])
                n += 1
            except Exception as e:  # e.g. the email was deleted since it was processed
                print(f"  could not label {row['id']}: {type(e).__name__}")
        print(f"Labelled {n} processed email(s).")
        return 0

    # Work out the window.
    run_started = int(time.time())
    if args.backfill:
        query = gmail.build_query(newer_than_days=args.backfill, all_categories=args.all_categories)
        mode = f"previous mail, last {args.backfill} days"
    else:
        last = state.get("last_run_at")
        if last:
            query = gmail.build_query(after_epoch=int(last) - OVERLAP_SECONDS, all_categories=args.all_categories)
            mode = f"new mail since {datetime.fromtimestamp(int(last)):%Y-%m-%d %H:%M}"
        else:
            query = gmail.build_query(newer_than_days=FIRST_RUN_DAYS, all_categories=args.all_categories)
            mode = f"first run, last {FIRST_RUN_DAYS} days"
    mode += ", all categories" if args.all_categories else ", Promotions and Social skipped"

    # Earlier failures go first, then the newest unprocessed mail, up to --max.
    done = state.done_ids()
    queue = state.retry_ids()[: args.max]
    seen, skipped, capped = set(queue), 0, False
    for msg_id in gmail.iter_message_ids(service, query):
        if msg_id in seen:
            continue
        if msg_id in done:
            skipped += 1
            continue
        if len(queue) >= args.max:
            capped = True
            break
        queue.append(msg_id)
        seen.add(msg_id)

    print(f"{mode}: {len(queue)} to process, {skipped} already done" + (" (more waiting)" if capped else "") + ".")
    if args.dry_run:
        for i, msg_id in enumerate(queue, 1):
            e = gmail.fetch_headers(service, msg_id)
            print(f"  [{i:>3}] {datetime.fromtimestamp(e['received_at']):%b %d %H:%M}  {e['subject'][:70]}  - {e['from'][:40]}")
        print("Dry run: no model calls, nothing saved.")
        return 0
    if not queue:
        if not args.backfill:
            state.set("last_run_at", str(run_started))
        return 0

    from agent.llm import LLM

    llm = LLM(cfg)
    try:
        warning = llm.check()
    except Exception as e:
        print(f"Model not reachable at {cfg.llm_base_url} ({type(e).__name__}). Is Ollama running?", file=sys.stderr)
        return 2
    if warning:
        print(warning, file=sys.stderr)
        return 2

    system = system_prompt()
    labeler = None if args.no_label else Labeler(service)
    labelled = label_errors = 0
    items, interrupted, t0 = [], False, time.time()
    try:
        for i, msg_id in enumerate(queue, 1):
            try:
                email = gmail.fetch(service, msg_id, cfg.body_chars)
            except Exception as e:
                # Not saved to state: if the message still exists, the next listing finds it again.
                email = {"id": msg_id, "received_at": run_started, "from": "", "subject": f"(could not fetch {msg_id})",
                         "snippet": "", "labels": [], "body": ""}
                items.append((email, Result(UNCLASSIFIED, error=f"fetch failed: {type(e).__name__}: {e}")))
                continue
            start = time.time()
            result = classify(llm, email, system)
            state.save(email, result, llm.model)
            items.append((email, result))
            note = ""
            if labeler and result.category != UNCLASSIFIED:
                try:
                    note = f"  -> {labeler.apply(msg_id, result.category)}"
                    labelled += 1
                except Exception as e:  # a label failure never stops the run
                    label_errors += 1
                    note = f"  (label failed: {type(e).__name__})"
            print(f"  [{i:>3}/{len(queue)}] {result.category:<12} {time.time() - start:5.1f}s  {email['subject'][:60]}{note}")
    except KeyboardInterrupt:
        interrupted = True
        print("\nStopped. Everything finished so far is saved; run the same command again to continue.")

    stamp = datetime.fromtimestamp(run_started)
    model_label = f"{llm.model} via {cfg.llm_base_url}"
    label = f"{stamp:%Y-%m-%d %H:%M}" + (" (stopped early)" if interrupted else "")
    report_path = cfg.out_dir / f"{'backfill' if args.backfill else 'summary'}-{stamp:%Y-%m-%d-%H%M}.md"
    labels_note = "off (--no-label)" if not labeler else f"{labelled} applied" + (f", {label_errors} failed" if label_errors else "")
    report_path.write_text(
        render_summary(items, run_label=label, mode=mode, model=model_label, skipped=skipped, labels=labels_note),
        encoding="utf-8",
    )
    todos_path.write_text(render_todos(state.open_todos()), encoding="utf-8")

    # The new-mail window only moves forward after a complete, uncapped run, so nothing is skipped.
    if not args.backfill and not interrupted and not capped:
        state.set("last_run_at", str(run_started))

    counts = Counter(r.category for _, r in items)
    print(f"\nDone in {time.time() - t0:.0f}s: " + ", ".join(f"{k} {v}" for k, v in counts.most_common()))
    if capped:
        print(f"More mail is waiting beyond --max {args.max}: run the same command again.")
    print(f"Report:  {report_path}\nTo-dos:  {todos_path}\nModel:   {model_label}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
