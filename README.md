# Google Drive 権限リセットツール

Removes public permissions ("anyone with the link" or domain-wide) from all files in your Google Drive.

## Prerequisites

### Google Cloud Console setup

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a project (or select an existing one)
3. Enable the following APIs:
   - [Google Drive API](https://console.developers.google.com/apis/api/drive.googleapis.com/)
   - [Google Sheets API](https://console.developers.google.com/apis/api/sheets.googleapis.com/) *(only needed if using `--spreadsheet`)*
4. Go to **APIs & Services → Credentials → Create Credentials → OAuth 2.0 Client ID**
5. Set Application type to **Desktop app**
6. Download the credentials and save as `credentials.json` in the project directory

---

## Running with Docker (Linux / Mac / Windows with Docker Desktop)

### First-time authentication

Authentication runs once and saves a `token.json` that is reused on subsequent runs.

**If your browser is on the same machine as Docker:**

```bash
make build
make auth
```

Copy the printed URL into your browser, complete the Google sign-in, and the token will be saved automatically.

**If running on a remote server (no browser):**

On a machine with a browser, open an SSH tunnel first:

```bash
ssh -L 8080:localhost:8080 your-server
```

Then on the server:

```bash
make auth
```

Open the printed URL in the browser on the other machine.

### Running

```bash
# Show files that would be affected (no changes made)
make dry-run

# Remove public permissions
make run

# Limit to first 10 files
make run ARGS='-n 10'

# Write results to a Google Spreadsheet
make dry-run ARGS="-s 'https://docs.google.com/spreadsheets/d/YOUR_ID/edit'"
```

---

## Running on Windows (standalone EXE)

### Download

Download `restrict_drive.exe` from the [Releases](../../releases) page.

### First-time authentication

Double-click `restrict_drive.exe` — it will open your browser automatically for Google sign-in. Once authorised, `token.json` is saved next to the exe and reused on subsequent runs.

### Usage

**Double-click** the exe to launch the interactive menu:

```
[1] ドライラン - 変更対象のファイルを確認する（変更なし）
[2] 実行       - 一般アクセス権限を削除する
[q] 終了
```

Or run from the command line:

```bat
restrict_drive.exe --dry-run
restrict_drive.exe --run
restrict_drive.exe --dry-run -n 10
restrict_drive.exe --dry-run -s "https://docs.google.com/spreadsheets/d/YOUR_ID/edit"
```

---

## Spreadsheet output

When `--spreadsheet URL` is provided, the tool clears the sheet and writes one row per affected file:

| 日時 | ファイル名 | URL | アクセス設定 | ステータス |
|------|-----------|-----|------------|----------|
| 2026-06-06 12:00:00 | example.pdf | https://... | リンクを知っている全員 | ドライラン（変更なし）|

Works with both `--dry-run` and `--run`.

---

## Configuration file

Create `config.json` in the same directory as the exe (or project root for Docker) to enable optional features. See `config.json.example` for the format.

| Key | Description |
|-----|-------------|
| `user_tracking_spreadsheet` | URL of a Google Spreadsheet used to track which users have run the tool and when |

**Example `config.json`:**

```json
{
  "user_tracking_spreadsheet": "https://docs.google.com/spreadsheets/d/YOUR_ID/edit"
}
```

After each successful run (not dry-run), the tool looks up the authenticated user's email address in the tracking spreadsheet:
- If the email exists, the **Last Run** date is updated
- If not, a new row is added with the email and current timestamp

**Tracking spreadsheet format:**

| メールアドレス | 最終実行日時 |
|---|---|
| user@example.com | 2026-06-06 12:00:00 |

If `config.json` is absent or the key is not set, user tracking is silently skipped.

---

## All options

| Option | Description |
|--------|-------------|
| `-d`, `--dry-run` | Show affected files without making changes |
| `-r`, `--run` | Remove public permissions |
| `-a`, `--auth` | Authenticate only, save `token.json` |
| `-n N`, `--max-items N` | Stop after N files |
| `-s URL`, `--spreadsheet URL` | Write results to a Google Spreadsheet |
| `--auth-port PORT` | Local port for OAuth callback (default: 8080) |
| `--no-browser` | Do not open browser automatically (used by Docker targets) |

---

## Building the Windows EXE

The exe is built automatically via GitHub Actions when a version tag is pushed.

### Setup

Add a repository secret named `CREDENTIALS_JSON` containing the base64-encoded contents of your `credentials.json`:

```bash
base64 -w 0 credentials.json
```

Copy the output and save it as the secret value in **GitHub → Settings → Secrets and variables → Actions**.

### Trigger a build

```bash
git tag v1.0.0
git push --tags
```

The built `restrict_drive.exe` will appear as a release asset.
