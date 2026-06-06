# ベースイメージ
FROM debian:trixie-slim

# システムパッケージのインストール
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    && rm -rf /var/lib/apt/lists/*

# 作業ディレクトリ
WORKDIR /app

# 仮想環境の作成
RUN python3 -m venv /app/venv
ENV PATH="/app/venv/bin:$PATH"

# 依存パッケージのインストール
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# スクリプトのコピー
COPY restrict_drive.py .

# 実行
ENTRYPOINT ["python", "restrict_drive.py"]
