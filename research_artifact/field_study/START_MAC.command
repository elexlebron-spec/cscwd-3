#!/bin/zsh
set -eu
cd -- "$(dirname -- "$0")"
printf '模式：PRACTICE 为练习，FORMAL 为正式记录。\n'
printf '输入模式 [PRACTICE]: '
read -r study_mode
study_mode=${study_mode:-PRACTICE}
if [[ "$study_mode" != "PRACTICE" && "$study_mode" != "FORMAL" ]]; then
  printf '只接受 PRACTICE 或 FORMAL。\n'
  exit 1
fi
study_label=$(date +%Y%m%d_%H%M%S)
printf '\n同一 Wi-Fi 下的其他设备，把角色链接中的 127.0.0.1 替换为本机局域网 IP。\n'
ipconfig getifaddr en0 || true
python3 server.py --host 0.0.0.0 --mode "$study_mode" --output "sessions/${study_mode}_${study_label}"
