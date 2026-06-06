import os
import json
import argparse
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

# 必要なスコープ
SCOPES = ['https://www.googleapis.com/auth/drive']

def authenticate():
    """Google Drive APIの認証"""
    creds = None

    # 既存トークンの読み込み
    if os.path.exists('token.json') and os.path.getsize('token.json') > 0:
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)

    # トークンがない or 期限切れの場合
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)

            flow.redirect_uri = 'urn:ietf:wg:oauth:2.0:oob'
            auth_url, _ = flow.authorization_url(prompt='consent')
            print(f"\n以下のURLをブラウザで開いてください:\n{auth_url}\n")
            code = input("認証コードを貼り付けてください: ")
            flow.fetch_token(code=code)
            creds = flow.credentials

        # トークンを保存
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
    parser.add_argument('-d', '--dry-run', action='store_true',
                        help='変更をせずに対象ファイルを表示のみ')
    parser.add_argument('-n', '--max-items', type=int, default=None,
                        help='処理する最大ファイル数')
    args = parser.parse_args()

    print("=== Google Drive 権限リセットツール ===\n")

    # 認証
    creds = authenticate()
    service = build('drive', 'v3', credentials=creds)

    # 全ファイル取得
    files = get_all_files(service)
    print(f"\n合計 {len(files)} 件のファイル・フォルダを取得\n")

    print("-" * 40)
    targets = []

    for file in files:
        if args.max_items and len(targets) >= args.max_items:
            break
        if restrict_file(service, file, dry_run=args.dry_run):
            targets.append(file)

    print("-" * 40)
    print(f"\n変更対象: {len(targets)} 件\n")

    if not targets:
        print("変更が必要なファイルはありません。")
        return

    if args.dry_run:
        print("ドライランモード: 変更は行いません。")
        return

    answer = input(f"{len(targets)} 件の一般アクセスを削除します。実行しますか？ (yes/no): ")
    if answer.lower() != 'yes':
        print("キャンセルしました。")
        return

    # --- 実際に実行 ---
    print("\n【実行中】")
    print("-" * 40)
    success = 0
    failed = 0

    for file in targets:
        result = restrict_file(service, file, dry_run=False)
        if result:
            success += 1
        else:
            failed += 1

    print("-" * 40)
    print(f"\n完了: 成功 {success} 件 / 失敗 {failed} 件")


if __name__ == '__main__':
    main()
