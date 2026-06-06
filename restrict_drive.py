import os
import re
import sys
import json
import argparse
from datetime import datetime
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from google.auth.exceptions import RefreshError

SCOPES = [
    'https://www.googleapis.com/auth/drive',
    'https://www.googleapis.com/auth/spreadsheets',
]

# Statuses that mean a file is fully processed — skip on subsequent runs.
DONE_STATUSES = {'変更なし', '制限済み'}


def get_app_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def get_credentials_path():
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, 'credentials.json')
    return os.path.join(get_app_dir(), 'credentials.json')


CREDENTIALS_PATH = get_credentials_path()
TOKEN_PATH = os.path.join(get_app_dir(), 'token.json')
CONFIG_PATH = os.path.join(get_app_dir(), 'config.json')


def load_config():
    if not os.path.exists(CONFIG_PATH):
        return {}
    with open(CONFIG_PATH) as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}


def get_user_email(service_drive):
    about = service_drive.about().get(fields='user').execute()
    return about['user']['emailAddress']


def update_user_tracking(creds, spreadsheet_id, email):
    service = build('sheets', 'v4', credentials=creds)
    sheets = service.spreadsheets()

    result = sheets.values().get(
        spreadsheetId=spreadsheet_id,
        range='A:A',
    ).execute()

    rows = result.get('values', [])
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    for i, row in enumerate(rows):
        if row and row[0] == email:
            sheets.values().update(
                spreadsheetId=spreadsheet_id,
                range=f'B{i + 1}',
                valueInputOption='RAW',
                body={'values': [[timestamp]]},
            ).execute()
            print(f"ユーザー追跡を更新しました: {email}")
            return

    sheets.values().append(
        spreadsheetId=spreadsheet_id,
        range='A:B',
        valueInputOption='RAW',
        insertDataOption='INSERT_ROWS',
        body={'values': [[email, timestamp]]},
    ).execute()
    print(f"ユーザー追跡に新規追加しました: {email}")


def authenticate(auth_port=8080, open_browser=True, allow_new_flow=True):
    creds = None

    if os.path.exists(TOKEN_PATH) and os.path.getsize(TOKEN_PATH) > 0:
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except RefreshError:
                print("トークンの更新に失敗しました。再認証します。token.jsonを削除します。")
                open(TOKEN_PATH, 'w').close()
                creds = None
        if not creds or not creds.valid:
            if not allow_new_flow:
                raise Exception(
                    "有効なtoken.jsonがありません。先に 'make auth' を実行してください。"
                )
            if not open_browser:
                print(f"\nポート {auth_port} でOAuthコールバックサーバーを起動します。")
                print(f"リモートサーバーの場合、別マシンから以下でSSHトンネルを張ってください:")
                print(f"  ssh -L {auth_port}:localhost:{auth_port} <このサーバー>\n")
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
            bind = '0.0.0.0' if not open_browser else '127.0.0.1'
            creds = flow.run_local_server(port=auth_port, open_browser=open_browser, bind_addr=bind)

        with open(TOKEN_PATH, 'w') as token:
            token.write(creds.to_json())

    return creds


def ensure_sheets_scope(creds, auth_port, open_browser):
    sheets_scope = 'https://www.googleapis.com/auth/spreadsheets'
    if creds.scopes and sheets_scope not in creds.scopes:
        print("スプレッドシートのアクセス権が必要なため再認証します。token.jsonを削除します。")
        open(TOKEN_PATH, 'w').close()
        return authenticate(auth_port=auth_port, open_browser=open_browser, allow_new_flow=True)
    return creds


def extract_spreadsheet_id(url):
    match = re.search(r'/spreadsheets/d/([a-zA-Z0-9-_]+)', url)
    if not match:
        raise ValueError(f"スプレッドシートURLからIDを取得できませんでした: {url}")
    return match.group(1)


def load_logged_file_ids(creds, spreadsheet_id, batch_size=1000):
    """Return the set of file IDs already logged with a done status, loaded in batches."""
    service = build('sheets', 'v4', credentials=creds)
    sheets = service.spreadsheets()

    done = set()
    start_row = 2  # row 1 is the header

    while True:
        end_row = start_row + batch_size - 1
        result = sheets.values().get(
            spreadsheetId=spreadsheet_id,
            range=f'B{start_row}:F{end_row}',
        ).execute()

        rows = result.get('values', [])
        for row in rows:
            if len(row) >= 5 and row[4] in DONE_STATUSES:
                done.add(row[0])

        if len(rows) < batch_size:
            break

        start_row += batch_size

    return done


def append_to_spreadsheet(creds, spreadsheet_id, rows):
    """Append rows to the log spreadsheet, writing a header first if the sheet is empty."""
    service = build('sheets', 'v4', credentials=creds)
    sheets = service.spreadsheets()

    existing = sheets.values().get(
        spreadsheetId=spreadsheet_id,
        range='A1:A1',
    ).execute()

    to_write = rows
    if not existing.get('values'):
        header = [['日時', 'ファイルID', 'ファイル名', 'URL', 'アクセス設定', 'ステータス']]
        to_write = header + rows

    sheets.values().append(
        spreadsheetId=spreadsheet_id,
        range='A:F',
        valueInputOption='RAW',
        insertDataOption='INSERT_ROWS',
        body={'values': to_write},
    ).execute()

    print(f"スプレッドシートに {len(rows)} 件を追記しました。")


def get_all_files(service, limit=None, skip_ids=None):
    items = []
    page_token = None
    skip_ids = skip_ids or set()

    print("ファイル一覧を取得中...")

    while True:
        response = service.files().list(
            q="trashed = false and 'me' in owners",
            spaces='drive',
            fields='nextPageToken, files(id, name, mimeType, webViewLink)',
            pageToken=page_token,
            pageSize=1000,
        ).execute()

        for file in response.get('files', []):
            if file['id'] not in skip_ids:
                items.append(file)
                if limit and len(items) >= limit:
                    print(f"  {len(items)}件取得済み...")
                    return items

        page_token = response.get('nextPageToken')
        print(f"  {len(items)}件取得済み...")

        if not page_token:
            break

    return items


def get_anyone_permission(service, file_id):
    try:
        perms = service.permissions().list(
            fileId=file_id,
            fields='permissions(id, type, domain)'
        ).execute()

        for perm in perms.get('permissions', []):
            if perm.get('type') in ('anyone', 'domain'):
                return perm

    except Exception:
        pass

    return None


def restrict_file(service, file, dry_run=True):
    """Returns (label, error) if the file has a public permission, (None, None) otherwise."""
    perm = get_anyone_permission(service, file['id'])

    if not perm:
        return None, None

    perm_type = perm.get('type')
    domain = perm.get('domain', '')
    label = 'ドメイン全員' if perm_type == 'domain' else 'リンクを知っている全員'
    if domain:
        label += f' ({domain})'

    print(f"  対象: {file['name']}")
    print(f"    現在の設定: {label}")

    if not dry_run:
        try:
            service.permissions().delete(
                fileId=file['id'],
                permissionId=perm['id']
            ).execute()
            print(f"    ✅ 制限済み")
        except Exception as e:
            if 'cannotDeletePermission' in str(e):
                print(f"    ⚠️ スキップ（親フォルダから継承された権限）")
                return label, "継承済み権限（削除不可）"
            print(f"    ❌ エラー: {e}")
            return label, str(e)

    return label, None


def interactive_mode():
    print("=== Google Drive 権限リセットツール ===\n")
    print("[1] ドライラン - 変更対象のファイルを確認する（変更なし）")
    print("[2] 実行       - 一般アクセス権限を削除する")
    print("[q] 終了\n")

    choice = input("選択してください: ").strip()

    if choice == '1':
        return 'dry-run'
    elif choice == '2':
        confirm = input("\n本当に実行しますか？ (yes/no): ").strip().lower()
        if confirm == 'yes':
            return 'run'
        print("キャンセルしました。")
    return None


def pause_on_exit():
    if getattr(sys, 'frozen', False) and sys.platform == 'win32':
        input("\nEnterキーを押して終了...")


def main():
    parser = argparse.ArgumentParser(description='Google Drive 権限リセットツール')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('-d', '--dry-run', action='store_true',
                      help='変更をせずに対象ファイルを表示のみ')
    mode.add_argument('-r', '--run', action='store_true',
                      help='一般アクセス権限を実際に削除する')
    mode.add_argument('-a', '--auth', action='store_true',
                      help='認証のみ実行してtoken.jsonを生成する')
    parser.add_argument('-n', '--max-items', type=int, default=None,
                        help='処理する最大ファイル数')
    parser.add_argument('-s', '--spreadsheet', metavar='URL',
                        help='ログを追記するGoogleスプレッドシートのURL')
    parser.add_argument('--auth-port', type=int, default=8080,
                        help='OAuthコールバック用ローカルポート (デフォルト: 8080)')
    parser.add_argument('--no-browser', action='store_true',
                        help='ブラウザを自動で開かない（リモートサーバー用）')

    interactive = False
    if len(sys.argv) == 1:
        mode_choice = interactive_mode()
        if not mode_choice:
            pause_on_exit()
            sys.exit(0)
        interactive = True
        args = parser.parse_args(['--dry-run' if mode_choice == 'dry-run' else '--run'])
    else:
        args = parser.parse_args()

    if not args.dry_run and not args.run and not args.auth:
        parser.print_help()
        sys.exit(0)

    if not interactive:
        print("=== Google Drive 権限リセットツール ===\n")

    config = load_config()

    if args.spreadsheet:
        try:
            extract_spreadsheet_id(args.spreadsheet)
        except ValueError as e:
            print(f"エラー: --spreadsheet の {e}")
            sys.exit(1)

    tracking_url = config.get('user_tracking_spreadsheet')
    if tracking_url:
        try:
            extract_spreadsheet_id(tracking_url)
        except ValueError as e:
            print(f"エラー: config.json の user_tracking_spreadsheet の {e}")
            sys.exit(1)

    is_docker_mode = args.no_browser
    creds = authenticate(
        auth_port=args.auth_port,
        open_browser=not is_docker_mode,
        allow_new_flow=True,
    )

    if args.auth:
        print("認証完了。token.jsonを保存しました。")
        pause_on_exit()
        return

    needs_sheets = args.spreadsheet or tracking_url
    if needs_sheets:
        creds = ensure_sheets_scope(creds, args.auth_port, not is_docker_mode)

    service_drive = build('drive', 'v3', credentials=creds)

    # Load already-processed file IDs from the log spreadsheet.
    logged_ids = set()
    if args.spreadsheet:
        spreadsheet_id = extract_spreadsheet_id(args.spreadsheet)
        logged_ids = load_logged_file_ids(creds, spreadsheet_id, batch_size=args.max_items or 1000)
        if logged_ids:
            print(f"ログ済みファイル {len(logged_ids)} 件をスキップします。\n")

    files = get_all_files(service_drive, limit=args.max_items, skip_ids=logged_ids)
    print(f"\n合計 {len(files)} 件のファイル・フォルダを取得\n")

    print("-" * 40)
    targets = []
    new_log_rows = []
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    total = len(files)
    for i, file in enumerate(files):
        remaining = total - i - 1
        print(f"[{i + 1}/{total}] {file['name']} (残り {remaining} 件)")

        label, error = restrict_file(service_drive, file, dry_run=not args.run)

        if label is not None:
            targets.append((file, label, error))

        if error:
            status = f'エラー: {error}'
        elif label is None:
            status = '変更なし'
        elif args.dry_run:
            status = 'ドライラン（変更なし）'
        else:
            status = '制限済み'

        new_log_rows.append([
            timestamp,
            file['id'],
            file['name'],
            file.get('webViewLink', ''),
            label or '',
            status,
        ])

    print("-" * 40)

    failures  = [t for t in targets if t[2]]
    successes = [t for t in targets if not t[2]]
    print(f"\n変更対象: {len(targets)} 件"
          + (f" ({len(failures)} 件エラー)" if failures else "")
          + (f" / スキップ済み: {len(logged_ids)} 件" if logged_ids else "") + "\n")

    if args.spreadsheet and new_log_rows:
        append_to_spreadsheet(creds, spreadsheet_id, new_log_rows)

    if not targets:
        print("変更が必要なファイルはありません。")
        pause_on_exit()
        return

    if args.dry_run:
        print("ドライランモード: 変更は行いません。")
        pause_on_exit()
        return

    print(f"\n完了: {len(successes)} 件の一般アクセスを削除しました。"
          + (f" ({len(failures)} 件失敗)" if failures else ""))

    if tracking_url and successes:
        tracking_id = extract_spreadsheet_id(tracking_url)
        email = get_user_email(service_drive)
        update_user_tracking(creds, tracking_id, email)

    pause_on_exit()


if __name__ == '__main__':
    main()
