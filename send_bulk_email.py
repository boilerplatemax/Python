"""
send_bulk_email.py — Send bulk emails via the SendGrid API.

Usage:
    python send_bulk_email.py leads.csv --start 1 --count 50

        --start   Which message number to start from in messages.csv (1-indexed).
        --count   How many message variations to send; each is sent to all recipients.

Requirements:
    pip install -r requirements.txt

.env file (place in the same directory as this script):
    SENDGRID_API_KEY=your_key_here
    FROM_EMAIL=noreply@uniontab.com
    FROM_NAME=UnionTab

leads.csv format:
    - Two columns: email, name
    - Header row expected: email,name
    - 'name' column is optional; if absent or empty, falls back to "Hello"

messages.csv format:
    - Two columns: subject, body
    - Header row expected: subject,body
    - 'body' supports multiline text (use quoted fields) and the {name} placeholder
    - Each row is a different message variation

Output:
    - Live success/failure status printed for each send.
    - failed_sends.csv written at the end with any addresses that failed.
    - Summary line: "X sent successfully, X failed."
"""

import argparse
import csv
import os
import random
import re
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail, From

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
FALLBACK_NAME = "Hello"


def is_valid_email(address: str) -> bool:
    return bool(EMAIL_RE.match(address.strip()))


def load_recipients(csv_path: str) -> list[tuple[str, str]]:
    """
    Read (email, name) pairs from a CSV file.

    Expects a header row with at least an 'email' column.  If a 'name' column
    is present its value is used for personalisation; missing or empty values
    fall back to FALLBACK_NAME.
    """
    path = Path(csv_path)
    if not path.exists():
        print(f"Error: CSV file '{csv_path}' not found.")
        sys.exit(1)

    recipients: list[tuple[str, str]] = []
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        rows = list(reader)

    if not rows:
        return recipients

    # Detect header and column positions
    has_header = rows[0] and rows[0][0].strip().lower() == "email"
    if has_header:
        header = [c.strip().lower() for c in rows[0]]
        name_col = header.index("name") if "name" in header else None
        start_index = 1
    else:
        name_col = None
        start_index = 0

    for row in rows[start_index:]:
        if not row:
            continue
        email = row[0].strip()
        if name_col is not None and len(row) > name_col:
            name = row[name_col].strip() or FALLBACK_NAME
        else:
            name = FALLBACK_NAME
        recipients.append((email, name))

    return recipients


def load_messages(csv_path: str = "messages.csv") -> list[tuple[str, str]]:
    """
    Read (subject, body) pairs from a CSV file.

    Expects a header row with 'subject' and 'body' columns.  The body field
    may contain newlines (standard quoted CSV multi-line values).  The {name}
    placeholder is substituted at send time.
    """
    path = Path(csv_path)
    if not path.exists():
        print(f"Error: messages file '{csv_path}' not found.")
        sys.exit(1)

    messages: list[tuple[str, str]] = []
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        rows = list(reader)

    if not rows:
        print("Error: messages.csv is empty.")
        sys.exit(1)

    has_header = rows[0] and rows[0][0].strip().lower() == "subject"
    start_index = 1 if has_header else 0

    for row in rows[start_index:]:
        if not row:
            continue
        subject = row[0].strip()
        body = row[1] if len(row) > 1 else ""
        messages.append((subject, body))

    return messages


def save_failed(failed: list[tuple[str, str]]) -> None:
    """Write failed addresses and reasons to failed_sends.csv."""
    out_path = Path("failed_sends.csv")
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["email", "reason"])
        writer.writerows(failed)
    print(f"\nFailed addresses saved to {out_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    # ── Arguments ──────────────────────────────────────────────────────────
    parser = argparse.ArgumentParser(
        description="Send bulk emails via the SendGrid API.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("leads_csv", help="Path to leads CSV file (columns: email, name)")
    parser.add_argument(
        "--start",
        type=int,
        default=1,
        metavar="N",
        help="Message number in messages.csv to start from, 1-indexed (default: 1)",
    )
    parser.add_argument(
        "--count",
        type=int,
        required=True,
        metavar="N",
        help="Number of message variations to send; each is sent to all recipients",
    )
    args = parser.parse_args()

    if args.start < 1:
        print("Error: --start must be >= 1")
        sys.exit(1)
    if args.count < 1:
        print("Error: --count must be >= 1")
        sys.exit(1)

    # ── Credentials ────────────────────────────────────────────────────────
    load_dotenv()

    api_key = os.getenv("SENDGRID_API_KEY")
    from_email = os.getenv("FROM_EMAIL")
    from_name = os.getenv("FROM_NAME")

    missing = [k for k, v in {
        "SENDGRID_API_KEY": api_key,
        "FROM_EMAIL": from_email,
        "FROM_NAME": from_name,
    }.items() if not v]

    if missing:
        print(f"Error: missing environment variable(s): {', '.join(missing)}")
        print("Create a .env file with SENDGRID_API_KEY, FROM_EMAIL, and FROM_NAME.")
        sys.exit(1)

    # ── Load recipients ────────────────────────────────────────────────────
    recipients = load_recipients(args.leads_csv)
    if not recipients:
        print("No email addresses found in the CSV file.")
        sys.exit(1)

    print(f"Loaded {len(recipients)} recipient(s) from '{args.leads_csv}'.")

    # ── Load messages ──────────────────────────────────────────────────────
    all_messages = load_messages("messages.csv")
    if not all_messages:
        print("No messages found in messages.csv.")
        sys.exit(1)

    print(f"Loaded {len(all_messages)} message variation(s) from 'messages.csv'.")

    if args.start > len(all_messages):
        print(
            f"Error: --start {args.start} exceeds the number of available "
            f"messages ({len(all_messages)})."
        )
        sys.exit(1)

    start_idx = args.start - 1  # convert to 0-indexed
    selected = all_messages[start_idx: start_idx + args.count]

    if len(selected) < args.count:
        print(
            f"Warning: only {len(selected)} message(s) available starting from "
            f"message {args.start} (requested {args.count}). Sending what's available."
        )

    print(
        f"\nWill send {len(selected)} message variation(s), "
        f"each to all {len(recipients)} recipient(s)."
    )
    print()

    # ── Send ───────────────────────────────────────────────────────────────
    client = SendGridAPIClient(api_key)
    sent = 0
    failed: list[tuple[str, str]] = []

    for msg_num, (subject, body_template) in enumerate(selected, start=args.start):
        print(f"--- Message {msg_num}: {subject!r} ---")

        for email, name in recipients:
            if not is_valid_email(email):
                reason = "malformed address"
                print(f"  SKIP   {email!r} — {reason}")
                failed.append((email, reason))
                continue

            body = body_template.replace("{name}", name)

            message = Mail(
                from_email=From(from_email, from_name),
                to_emails=email,
                subject=subject,
                plain_text_content=body,
            )

            try:
                response = client.send(message)
                if 200 <= response.status_code < 300:
                    print(f"  OK     {email} ({name})")
                    sent += 1
                else:
                    reason = f"HTTP {response.status_code}"
                    print(f"  FAIL   {email} — {reason}")
                    failed.append((email, reason))
            except Exception as exc:
                reason = str(exc)
                print(f"  FAIL   {email} — {reason}")
                failed.append((email, reason))

            time.sleep(random.uniform(3, 7))

        print()

    # ── Results ────────────────────────────────────────────────────────────
    if failed:
        save_failed(failed)

    print(f"Summary: {sent} sent successfully, {len(failed)} failed.")


if __name__ == "__main__":
    main()
