"""
send_bulk_email.py — Send bulk emails via the SendGrid API.

Usage:
    python send_bulk_email.py leads.csv

Requirements:
    pip install -r requirements.txt

.env file (place in the same directory as this script):
    SENDGRID_API_KEY=your_key_here
    FROM_EMAIL=noreply@uniontab.com
    FROM_NAME=UnionTab

CSV format:
    - Single column of email addresses.
    - Optional header row named "email" (case-insensitive).
    - If no recognised header is found, every row is treated as an address.

Output:
    - Live success/failure status printed for each send.
    - failed_sends.csv written at the end with any addresses that failed.
    - Summary line: "X sent successfully, X failed."
"""

import csv
import re
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
import os

from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail, From

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def is_valid_email(address: str) -> bool:
    return bool(EMAIL_RE.match(address.strip()))


def load_emails(csv_path: str) -> list[str]:
    """
    Read email addresses from a CSV file.

    Accepts files with or without a header row.  If the first cell of the
    first row matches 'email' (case-insensitive) it is treated as a header
    and skipped; otherwise every row is read as an address.
    """
    path = Path(csv_path)
    if not path.exists():
        print(f"Error: CSV file '{csv_path}' not found.")
        sys.exit(1)

    emails: list[str] = []
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        rows = list(reader)

    if not rows:
        return emails

    # Detect header
    start_index = 0
    if rows[0] and rows[0][0].strip().lower() == "email":
        start_index = 1

    for row in rows[start_index:]:
        if row:
            emails.append(row[0].strip())

    return emails


def prompt_body() -> str:
    """Prompt the user for a multiline email body, terminated by a lone '.'."""
    print("Enter email body (type a single '.' on its own line to finish):")
    lines: list[str] = []
    while True:
        line = input()
        if line == ".":
            break
        lines.append(line)
    return "\n".join(lines)


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
    if len(sys.argv) != 2:
        print("Usage: python send_bulk_email.py <path/to/leads.csv>")
        sys.exit(1)

    csv_file = sys.argv[1]

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
    all_emails = load_emails(csv_file)
    if not all_emails:
        print("No email addresses found in the CSV file.")
        sys.exit(1)

    print(f"Loaded {len(all_emails)} address(es) from '{csv_file}'.")

    # ── Compose message ────────────────────────────────────────────────────
    subject = input("\nSubject: ").strip()
    if not subject:
        print("Error: subject cannot be empty.")
        sys.exit(1)

    body = prompt_body()
    if not body.strip():
        print("Error: email body cannot be empty.")
        sys.exit(1)

    print()  # blank line before send log

    # ── Send ───────────────────────────────────────────────────────────────
    client = SendGridAPIClient(api_key)
    sent = 0
    failed: list[tuple[str, str]] = []

    for address in all_emails:
        # Validate address format
        if not is_valid_email(address):
            reason = "malformed address"
            print(f"  SKIP   {address!r} — {reason}")
            failed.append((address, reason))
            continue

        message = Mail(
            from_email=From(from_email, from_name),
            to_emails=address,
            subject=subject,
            plain_text_content=body,
        )

        try:
            response = client.send(message)
            if 200 <= response.status_code < 300:
                print(f"  OK     {address}")
                sent += 1
            else:
                reason = f"HTTP {response.status_code}"
                print(f"  FAIL   {address} — {reason}")
                failed.append((address, reason))
        except Exception as exc:
            reason = str(exc)
            print(f"  FAIL   {address} — {reason}")
            failed.append((address, reason))

        time.sleep(1)

    # ── Results ────────────────────────────────────────────────────────────
    if failed:
        save_failed(failed)

    print(f"\nSummary: {sent} sent successfully, {len(failed)} failed.")


if __name__ == "__main__":
    main()
