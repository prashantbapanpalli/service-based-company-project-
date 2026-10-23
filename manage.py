"""Leads and reports from the command line.

    python manage.py import data/sample_leads.csv   add leads (skips opt-outs, duplicates, bad numbers)
    python manage.py leads [--status new]           list leads
    python manage.py next                           next lead that may be called now, or why not
    python manage.py check 98765 43210              may this number be called now?
    python manage.py optout 98765 43210             block a number permanently
    python manage.py callbacks | handovers          pending callbacks / people Chetan must call
    python manage.py done handovers 3               mark item 3 as done
    python manage.py demos                          booked demos
    python manage.py calls [--limit 20]             recent calls with outcome and cost
    python manage.py report                         totals: outcomes, cost per call, opt-outs
    python manage.py export calls.csv               all calls to CSV
    python manage.py check-kb                       validate knowledge base, playbook and scenarios
"""

import argparse
import csv
import sys

from app.db import Database, normalize_phone
from app.knowledge import check_playbook, load_kb, load_playbook
from app.scenarios import check_scenarios, load_scenarios


def show(rows, columns):
    if not rows:
        print("(none)")
        return
    widths = {c: max(len(c), *(len(str(r[c] if r[c] is not None else "")) for r in rows)) for c in columns}
    print("  ".join(c.ljust(widths[c]) for c in columns))
    for r in rows:
        print("  ".join(str(r[c] if r[c] is not None else "").ljust(widths[c]) for c in columns))


def check_kb():
    kb = load_kb()
    problems = check_playbook(load_playbook()) + check_scenarios(load_scenarios())
    for p in kb["products"]:
        if "price_approved" not in p:
            problems.append(f"product {p['name']}: missing price_approved")
    for p in problems:
        print("✗", p)
    print("OK" if not problems else f"{len(problems)} problem(s)")
    return 1 if problems else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="SourceCode Studio sales agent: leads and reports")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("import").add_argument("csv")
    sub.add_parser("leads").add_argument("--status")
    sub.add_parser("next")
    sub.add_parser("check").add_argument("phone", nargs="+")
    sub.add_parser("optout").add_argument("phone", nargs="+")
    sub.add_parser("callbacks")
    sub.add_parser("handovers")
    done = sub.add_parser("done")
    done.add_argument("table", choices=["callbacks", "handovers"])
    done.add_argument("id", type=int)
    sub.add_parser("demos")
    sub.add_parser("calls").add_argument("--limit", type=int, default=20)
    sub.add_parser("report")
    sub.add_parser("export").add_argument("csv")
    sub.add_parser("check-kb")
    args = parser.parse_args(argv)

    if args.cmd == "check-kb":
        return check_kb()

    db = Database(kb=load_kb())
    try:
        if args.cmd == "import":
            print(db.import_csv(args.csv))
        elif args.cmd == "leads":
            show(db.leads(args.status), ["id", "phone", "name", "business", "status", "attempts", "last_called_at"])
        elif args.cmd == "next":
            lead = db.next_lead()
            if lead:
                show([lead], ["id", "phone", "name", "business", "status", "attempts"])
            else:
                print("No lead may be called right now.")
                for lead in db.leads()[:10]:
                    print(f"  {lead['phone']}: {db.why_not_callable(lead) or 'ok'}")
        elif args.cmd in ("check", "optout"):
            phone = normalize_phone(" ".join(args.phone))
            if not phone:
                print("Not a valid Indian phone number.")
                return 1
            if args.cmd == "optout":
                db.opt_out(phone, "added manually")
                print(f"{phone} is blocked permanently.")
            else:
                lead = db.get_lead(phone)
                if lead is None:
                    print(f"{phone}: not in leads" + (" (opted out)" if db.is_opted_out(phone) else ""))
                else:
                    print(f"{phone}: {db.why_not_callable(lead) or 'may be called now'}")
        elif args.cmd == "callbacks":
            show(db.pending("callbacks"), ["id", "phone", "due_at", "note"])
        elif args.cmd == "handovers":
            show(db.pending("handovers"), ["id", "phone", "reason", "preferred_time", "created_at"])
        elif args.cmd == "done":
            db.mark_done(args.table, args.id)
            print("Done.")
        elif args.cmd == "demos":
            show(db.conn.execute("SELECT * FROM demos ORDER BY id").fetchall(), ["id", "phone", "when_text", "place", "note"])
        elif args.cmd == "calls":
            show(db.recent_calls(args.limit), ["id", "phone", "started_at", "duration_s", "outcome", "cost_inr", "notes"])
        elif args.cmd == "report":
            for key, value in db.report().items():
                print(f"{key}: {value}")
        elif args.cmd == "export":
            rows = db.conn.execute("SELECT * FROM calls ORDER BY id").fetchall()
            with open(args.csv, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(rows[0].keys() if rows else ["id"])
                writer.writerows([tuple(r) for r in rows])
            print(f"Wrote {len(rows)} calls to {args.csv}")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
