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


def get_app_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def get_credentials_path():
    # When bundled by PyInstaller, credentials.json is in the temp _MEIPASS dir.
    # At runtime (unfrozen or for token.json), use the exe/script directory.
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
    """Re-authenticate if the Sheets scope is missing from the saved token."""
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


def write_to_spreadsheet(creds, spreadsheet_id, targets, dry_run):
    service = build('sheets', 'v4', credentials=creds)
    sheets = service.spreadsheets()

    sheets.values().clear(
        spreadsheetId=spreadsheet_id,
        range='A:Z',
    ).execute()

    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    rows = [['日時', 'ファイル名', 'URL', 'アクセス設定', 'ステータス']]
    for file, label, error in targets:
        if error:
            status = f'エラー: {error}'
        elif dry_run:
            status = 'ドライラン（変更なし）'
        else:
            status = '制限済み'
        rows.append([timestamp, file['name'], file.get('webViewLink', ''), label, status])

    sheets.values().update(
        spreadsheetId=spreadsheet_id,
        range='A1',
        valueInputOption='RAW',
        body={'values': rows},
    ).execute()

    print(f"スプレッドシートに {len(targets)} 件を書き込みました。")


def get_all_files(service, limit=None):
    items = []
    page_token = None

    print("ファイル一覧を取得中...")

    while True:
        page_size = min(1000, limit - len(items)) if limit else 1000
        response = service.files().list(
            q="trashed = false and 'me' in owners",
            spaces='drive',
            fields='nextPageToken, files(id, name, mimeType, webViewLink)',
            pageToken=page_token,
            pageSize=page_size
        ).execute()

        items.extend(response.get('files', []))
        page_token = response.get('nextPageToken')

        print(f"  {len(items)}件取得済み...")

        if not page_token or (limit and len(items) >= limit):
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
    """Returns (label, error) if the file has a public permission, (None, None) otherwise.
    On success error is None; on delete failure error is the exception string."""
    file_id = file['id']
    file_name = file['name']

    perm = get_anyone_permission(service, file_id)

    if not perm:
        return None, None

    perm_type = perm.get('type')
    domain = perm.get('domain', '')
    label = 'ドメイン全員' if perm_type == 'domain' else 'リンクを知っている全員'
    if domain:
        label += f' ({domain})'

    print(f"  対象: {file_name}")
    print(f"    現在の設定: {label}")

    if not dry_run:
        try:
            service.permissions().delete(
                fileId=file_id,
                permissionId=perm['id']
            ).execute()
            print(f"    ✅ 制限済み")
        except Exception as e:
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
                        help='結果を書き込むGoogleスプレッドシートのURL')
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

    needs_sheets = args.spreadsheet or config.get('user_tracking_spreadsheet')
    if needs_sheets:
        creds = ensure_sheets_scope(creds, args.auth_port, not is_docker_mode)

    service_drive = build('drive', 'v3', credentials=creds)

    files = get_all_files(service_drive, limit=args.max_items)
    print(f"\n合計 {len(files)} 件のファイル・フォルダを取得\n")

    print("-" * 40)
    targets = []

    total = len(files)
    for i, file in enumerate(files):
        remaining = total - i - 1
        print(f"[{i + 1}/{total}] {file['name']} (残り {remaining} 件)")
        label, error = restrict_file(service_drive, file, dry_run=not args.run)
        if label is not None:
            targets.append((file, label, error))

    print("-" * 40)

    failures  = [t for t in targets if t[2]]
    successes = [t for t in targets if not t[2]]
    print(f"\n変更対象: {len(targets)} 件"
          + (f" ({len(failures)} 件エラー)" if failures else "") + "\n")

    if not targets:
        print("変更が必要なファイルはありません。")
        pause_on_exit()
        return

    if args.spreadsheet:
        spreadsheet_id = extract_spreadsheet_id(args.spreadsheet)
        write_to_spreadsheet(creds, spreadsheet_id, targets, dry_run=not args.run)

    if args.dry_run:
        print("ドライランモード: 変更は行いません。")
        pause_on_exit()
        return

    print(f"\n完了: {len(successes)} 件の一般アクセスを削除しました。"
          + (f" ({len(failures)} 件失敗)" if failures else ""))

    tracking_url = config.get('user_tracking_spreadsheet')
    if tracking_url and successes:
        tracking_id = extract_spreadsheet_id(tracking_url)
        email = get_user_email(service_drive)
        update_user_tracking(creds, tracking_id, email)

    pause_on_exit()


if __name__ == '__main__':
    main()
