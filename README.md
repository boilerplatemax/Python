# Bulk Email Sender

A Python CLI tool for sending personalized bulk emails via the [SendGrid](https://sendgrid.com) API. Reads recipients from a CSV file and sends one or more message variations to each, with name personalization and rate limiting built in.

## Prerequisites

- Python 3.10+
- A [SendGrid](https://sendgrid.com) account with a verified sender email address
- A SendGrid API key with **Mail Send** permissions

## Setup

### 1. Clone the repository

```bash
git clone <repo-url>
cd Python
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment variables

Copy the example env file and fill in your credentials:

```bash
cp .env.example .env
```

Edit `.env`:

```
SENDGRID_API_KEY=your_sendgrid_api_key_here
FROM_EMAIL=you@yourdomain.com
FROM_NAME=Your Name or Company
```

| Variable | Description |
|---|---|
| `SENDGRID_API_KEY` | Your SendGrid API key |
| `FROM_EMAIL` | Sending address (must be verified in SendGrid) |
| `FROM_NAME` | Display name shown to recipients |

## CSV File Formats

### `leads.csv` — recipient list

```
email,name
john.doe@example.com,John
jane.smith@example.com,Jane
```

- `email` — recipient address (required)
- `name` — first name used for personalization (optional; defaults to `"Hello"`)

### `messages.csv` — email templates

```
subject,body
"A quick note for {name}","Hi {name},\n\nYour message here..."
```

- `{name}` in either column is replaced with the recipient's name at send time.

## Usage

```bash
python send_bulk_email.py <leads_file> [--start N] [--count N]
```

| Argument | Default | Description |
|---|---|---|
| `leads_file` | _(required)_ | Path to your recipients CSV |
| `--start N` | `1` | First message number to send (1-indexed) |
| `--count N` | `1` | Number of message variations to send |

### Examples

Send the first message to everyone in `leads.csv`:

```bash
python send_bulk_email.py leads.csv
```

Send messages 1 through 5:

```bash
python send_bulk_email.py leads.csv --start 1 --count 5
```

Send messages 10 through 14 (start at 10, send 5):

```bash
python send_bulk_email.py leads.csv --start 10 --count 5
```

## Output

Progress is printed to the console as emails are sent:

```
Loaded 3 recipient(s) from 'leads.csv'.
Loaded 60 message variation(s) from 'messages.csv'.

Will send 2 message variation(s), each to all 3 recipient(s).

--- Message 1: 'A quick note for {name}' ---
  OK     john.doe@example.com (John)
  OK     jane.smith@example.com (Jane)
  FAIL   bad-email (malformed address)

--- Message 2: 'Checking in, {name}' ---
  ...

Summary: 5 sent successfully, 1 failed.
```

Any failed sends are saved to `failed_sends.csv` with the reason for failure.

## Notes

- A random 3–7 second delay is added between sends to respect SendGrid rate limits.
- Basic email format validation is performed before each send attempt.
