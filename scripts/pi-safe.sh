#!/usr/bin/env bash
# pi-safe.sh — Pi を独立したDocker状態領域で実行するラッパー
#
# 既定では workspace を read-only でmountする。ホストの ~/.pi/agent は
# 決してmountしない。モデル呼び出しには --network bridge、書込みには
# --write-workspace をそれぞれ明示する。
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PI_VERSION="${PI_SAFE_PI_VERSION:-0.84.1}"
IMAGE="${PI_SAFE_IMAGE:-harunon-pi-safe:${PI_VERSION}}"
AGENT_STATE="${PI_SAFE_AGENT_DIR:-${HOME}/.pi-safe/agent}"
NETWORK="bridge"
WRITE_WORKSPACE=false
BUILD=false
DRY_RUN=false
PI_ARGS=()

usage() {
  cat <<'USAGE'
Usage: ./scripts/pi-safe.sh [options] [-- pi-options...]

Run Pi in a Docker container without mounting the host ~/.pi/agent.
The current workspace is read-only unless --write-workspace is given.

Options:
  --build                 Build the pinned image before running
  --image IMAGE           Docker image (default: harunon-pi-safe:0.84.1)
  --agent-state DIR       Isolated Pi state directory (default: ~/.pi-safe/agent)
  --network MODE          bridge or none (default: bridge)
  --write-workspace       Mount the current workspace read-write
  --dry-run               Print the Docker command without running it
  -h, --help              Show this help

Examples:
  ./scripts/pi-safe.sh --dry-run --network none -- pi --version
  ./scripts/pi-safe.sh --network bridge --write-workspace -- "Review this repository"
  ./scripts/pi-safe.sh --build --network bridge -- pi --mode rpc

Security boundary:
  - Host ~/.pi/agent and its credentials are not mounted.
  - The workspace is read-only by default.
  - --network bridge allows outbound network access for model calls.
  - This is not a substitute for reviewing prompts, skills, or extensions.
USAGE
}

die() {
  printf 'ERROR: %s\n' "$1" >&2
  exit 2
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --build)
      BUILD=true
      shift
      ;;
    --image)
      [[ $# -ge 2 ]] || die "--image requires a value"
      IMAGE="$2"
      shift 2
      ;;
    --agent-state)
      [[ $# -ge 2 ]] || die "--agent-state requires a value"
      AGENT_STATE="$2"
      shift 2
      ;;
    --network)
      [[ $# -ge 2 ]] || die "--network requires a value"
      NETWORK="$2"
      shift 2
      ;;
    --write-workspace)
      WRITE_WORKSPACE=true
      shift
      ;;
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --)
      shift
      PI_ARGS=("$@")
      break
      ;;
    *)
      die "unknown wrapper argument: $1 (Pi optionsは -- の後ろに指定してください)"
      ;;
  esac
done

[[ "$NETWORK" == "bridge" || "$NETWORK" == "none" ]] || die "--network は bridge または none です"
[[ "$IMAGE" =~ ^[A-Za-z0-9][A-Za-z0-9._:/@-]*$ ]] || die "不正なDocker image名です"
[[ "$PI_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "PI_SAFE_PI_VERSION は semver 形式です"
command -v docker >/dev/null 2>&1 || die "docker が見つかりません"

if ! $DRY_RUN && ! docker info >/dev/null 2>&1; then
  if command -v orbctl >/dev/null 2>&1; then
    orb_status="$(orbctl status 2>/dev/null || true)"
    case "$orb_status" in
      *Stopped*)
        die "Docker daemonが停止しています（OrbStack=Stopped）。orbctl start 後に再実行してください"
        ;;
    esac
  fi
  die "Docker daemonに接続できません。docker contextとdaemonの状態を確認してください"
fi

workspace="$(pwd -P)"
workspace_mode="ro"
if $WRITE_WORKSPACE; then
  workspace_mode="rw"
fi

build_args=(docker build --file "$REPO_ROOT/scripts/pi-safe.Dockerfile" --tag "$IMAGE" --build-arg "PI_VERSION=$PI_VERSION" "$REPO_ROOT/scripts")
if $BUILD; then
  if $DRY_RUN; then
    printf '+ '
    printf '%q ' "${build_args[@]}"
    printf '\n'
  else
    "${build_args[@]}"
  fi
fi

if ! $DRY_RUN; then
  docker image inspect "$IMAGE" >/dev/null 2>&1 || die "imageがありません。--buildで作成してください: $IMAGE"
  mkdir -p "$AGENT_STATE"
  chmod 700 "$AGENT_STATE"
fi

if [[ -t 0 && -t 1 ]]; then
  tty_args=(-it)
else
  tty_args=(-i)
fi

docker_args=(
  docker run --rm "${tty_args[@]}"
  --network "$NETWORK"
  --workdir /workspace
  --volume "${workspace}:/workspace:${workspace_mode}"
  --volume "${AGENT_STATE}:/root/.pi/agent:rw"
)
if [[ "$NETWORK" == "none" ]]; then
  docker_args+=(--env PI_OFFLINE=1)
fi
docker_args+=("$IMAGE")
docker_args+=("${PI_ARGS[@]}")

printf 'workspace: %s (%s)\n' "$workspace" "$workspace_mode"
printf 'agent state: %s (isolated)\n' "$AGENT_STATE"
printf 'network: %s\n' "$NETWORK"
if $DRY_RUN; then
  printf '+ '
  printf '%q ' "${docker_args[@]}"
  printf '\n'
  exit 0
fi

exec "${docker_args[@]}"
