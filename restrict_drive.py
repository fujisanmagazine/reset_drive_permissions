import os
import sys
import argparse
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# 必要なスコープ
SCOPES = ['https://www.googleapis.com/auth/drive']

def authenticate(auth_port=8080):
    """Google Drive APIの認証 (OAuth2 InstalledAppFlow)"""
    creds = None

    if os.path.exists('token.json') and os.path.getsize('token.json') > 0:
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            print(f"\nポート {auth_port} でOAuthコールバックサーバーを起動します。")
            print(f"コンソール専用マシンの場合、別マシンから以下でSSHトンネルを張ってください:")
            print(f"  ssh -L {auth_port}:localhost:{auth_port} <このサーバー>\n")
            creds = flow.run_local_server(port=auth_port, open_browser=False)

        with open('token.json', 'w') as token:
            token.write(creds.to_json())

    return creds


def get_all_files(service):
    """マイドライブの全ファイル・フォルダを取得"""
    items = []
    page_token = None

    print("ファイル一覧を取得中...")

    while True:
        response = service.files().list(
            q="trashed = false",
            spaces='drive',
            fields='nextPageToken, files(id, name, mimeType)',
            pageToken=page_token,
            pageSize=1000
        ).execute()

        items.extend(response.get('files', []))
        page_token = response.get('nextPageToken')

        print(f"  {len(items)}件取得済み...")

        if not page_token:
            break

    return items


def get_anyone_permission(service, file_id):
    """'anyone' または 'domain' タイプの権限を取得"""
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
    """
    ファイルの一般アクセス権限を削除してオーナーのみに制限。
    dry_run=True の場合は実際には変更しない（確認用）
    """
    file_id = file['id']
    file_name = file['name']

    perm = get_anyone_permission(service, file_id)

    if not perm:
        return False  # すでに制限済み

    perm_type = perm.get('type')
    domain = perm.get('domain', '')

    label = 'ドメイン全員' if perm_type == 'domain' else 'リンクを知っている全員'
    print(f"  対象: {file_name}")
    print(f"    現在の設定: {label} {f'({domain})' if domain else ''}")

    if not dry_run:
        try:
            service.permissions().delete(
                fileId=file_id,
                permissionId=perm['id']
            ).execute()
            print(f"    ✅ 制限済み")
        except Exception as e:
            print(f"    ❌ エラー: {e}")
            return False

    return True


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
    parser.add_argument('--auth-port', type=int, default=8080,
                        help='OAuthコールバック用ローカルポート (デフォルト: 8080)')

    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(0)

    args = parser.parse_args()

    if not args.dry_run and not args.run and not args.auth:
        parser.print_help()
        sys.exit(0)

    print("=== Google Drive 権限リセットツール ===\n")

    # 認証
    creds = authenticate(auth_port=args.auth_port)

    if args.auth:
        print("認証完了。token.jsonを保存しました。")
        return
    service = build('drive', 'v3', credentials=creds)

    # 全ファイル取得
    files = get_all_files(service)
    print(f"\n合計 {len(files)} 件のファイル・フォルダを取得\n")

    print("-" * 40)
    targets = []

    for file in files:
        if args.max_items and len(targets) >= args.max_items:
            break
        if restrict_file(service, file, dry_run=not args.run):
            targets.append(file)

    print("-" * 40)
    print(f"\n変更対象: {len(targets)} 件\n")

    if not targets:
        print("変更が必要なファイルはありません。")
        return

    if args.dry_run:
        print("ドライランモード: 変更は行いません。")
        return

    print(f"\n完了: {len(targets)} 件の一般アクセスを削除しました。")


if __name__ == '__main__':
    main()
