#!/bin/bash
# 本机构建 doubaoime-asr 镜像 → push 到 NAS 私有 registry → scp compose 文件 → ssh NAS 拉镜像并启动
# NAS 上不需要 git pull，构建只在本机
# 用法: bash deploy-local.sh [--skip-build] [--build-proxy URL] [--tag VERSION]
set -e

# --- 加载 .env（所有环境字符串必须来自 .env，脚本不带默认值） ---
if [ ! -f .env ]; then
  echo "ERROR: .env not found. Copy .env.example to .env and fill in your NAS info." >&2
  exit 1
fi
set -a; source .env; set +a

for var in REGISTRY NAS_USER NAS_HOST NAS_DIR; do
  if [ -z "${!var}" ]; then
    echo "ERROR: $var is empty in .env" >&2
    exit 1
  fi
done

IMAGE_BASE="$REGISTRY/doubaoime-asr"
STATE_FILE=".deploy-state"

SKIP_BUILD=false
BUILD_PROXY=""
VERSION=$(date +%Y%m%d-%H%M%S)-$(git rev-parse --short HEAD)

usage() {
  echo "Usage: $0 [options]"
  echo "  --skip-build       跳过 docker build，只 push + 部署"
  echo "  --build-proxy URL  docker build 代理（pip 加速）"
  echo "  --tag VERSION      覆盖自动生成的版本号"
  exit 1
}

while [[ $# -gt 0 ]]; do
  case $1 in
    --skip-build) SKIP_BUILD=true; shift ;;
    --build-proxy) BUILD_PROXY="$2"; shift 2 ;;
    --tag) VERSION="$2"; shift 2 ;;
    -h|--help) usage ;;
    *) echo "Unknown option: $1"; usage ;;
  esac
done

# --- 读取上次部署状态 ---
IMAGE_TAG=""
if [ -f "$STATE_FILE" ]; then
  set -a; source "$STATE_FILE"; set +a
fi

# --- 判断是否需要构建（路径无改动且有上次 tag 时跳过） ---
needs_build() {
  if [ "$SKIP_BUILD" = true ]; then return 1; fi
  if [ -z "$IMAGE_TAG" ]; then return 0; fi

  local prev_commit
  prev_commit=$(echo "$IMAGE_TAG" | sed 's/.*-//')
  if [ -z "$prev_commit" ] || ! git cat-file -e "$prev_commit" 2>/dev/null; then
    return 0
  fi

  if ! git diff --quiet "$prev_commit" HEAD -- doubaoime_asr/ examples/ samples/ Dockerfile pyproject.toml; then
    return 0
  fi
  return 1
}

# --- 构建 + 推送 ---
if needs_build; then
  export no_proxy="${no_proxy:+$no_proxy,}$NAS_HOST"
  PROXY_ARGS=""
  if [ -n "$BUILD_PROXY" ]; then
    PROXY_ARGS="--build-arg HTTP_PROXY=$BUILD_PROXY --build-arg HTTPS_PROXY=$BUILD_PROXY"
  fi

  echo "==> Building $IMAGE_BASE:$VERSION ..."
  docker build $PROXY_ARGS \
    -t "$IMAGE_BASE:latest" \
    -t "$IMAGE_BASE:$VERSION" \
    .

  echo "==> Pushing $IMAGE_BASE:latest and :$VERSION ..."
  docker push "$IMAGE_BASE:latest"
  docker push "$IMAGE_BASE:$VERSION"

  IMAGE_TAG="$VERSION"
else
  echo "==> No source changes since $IMAGE_TAG, skipping build"
fi

# --- 写回状态文件 ---
cat > "$STATE_FILE" << EOF
IMAGE_TAG=$IMAGE_TAG
EOF

# --- 同步 compose 文件到 NAS ---
# 假设 NAS_DIR 已由用户手动 git clone 创建
echo "==> Syncing docker-compose.prod.yml to $NAS_HOST:$NAS_DIR ..."
scp -o StrictHostKeyChecking=no docker-compose.prod.yml "$NAS_USER@$NAS_HOST:$NAS_DIR/docker-compose.prod.yml"

# 把 REGISTRY + IMAGE_TAG 写进 NAS 上的 .env，让 compose 插值时拿到完整 image
echo "==> Writing $NAS_DIR/.env (REGISTRY + IMAGE_TAG) ..."
ssh -o StrictHostKeyChecking=no "$NAS_USER@$NAS_HOST" \
  "printf 'REGISTRY=%s\nIMAGE_TAG=%s\n' '$REGISTRY' '$IMAGE_TAG' > $NAS_DIR/.env"

# --- NAS 拉镜像并重启 ---
# Synology 上非 root 用户没有 docker.sock 权限，必须 sudo；
# 又因为 sshd 非交互 shell 不加载 /etc/profile，docker 不在 PATH 里，sudo 内部要显式补 PATH
echo "==> Pulling image and restarting container on NAS..."
ssh -t -o StrictHostKeyChecking=no "$NAS_USER@$NAS_HOST" \
  "sudo sh -c 'export PATH=/usr/local/bin:/usr/bin:/bin:\$PATH && \
   cd $NAS_DIR && \
   docker compose -f docker-compose.prod.yml pull && \
   docker compose -f docker-compose.prod.yml up -d'"

# --- 追加 RELEASES.md ---
RELEASES_FILE="RELEASES.md"
if [ ! -f "$RELEASES_FILE" ]; then
  echo "# Releases" > "$RELEASES_FILE"
  echo "" >> "$RELEASES_FILE"
fi
{
  echo "## $(date '+%Y-%m-%d %H:%M:%S') | $VERSION"
  echo "$(git log -1 --pretty=%s)"
  echo ""
} >> "$RELEASES_FILE"

echo "==> Done. Deployed $IMAGE_BASE:$IMAGE_TAG to $NAS_HOST"
