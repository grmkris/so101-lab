#!/bin/bash
# MolmoAct2 policy-server bring-up for a Colab GPU runtime (L4/A100, bf16).
# Joins the tailnet (userspace), installs lerobot v0.6.0 with the molmoact2
# async whitelist patch, snapshots the SO-101 checkpoint as bf16, serves :8080.
#
# Colab cell:
#   import os; os.environ["TSKEY"] = "tskey-auth-..."   # ephemeral key
#   !curl -sL https://raw.githubusercontent.com/grmkris/so101-lab/main/gemini_er/colab_policy_server.sh | bash
set -e

echo "=== [1/5] tailscale (userspace) ==="
curl -fsSL https://tailscale.com/install.sh | sh >/dev/null
nohup tailscaled --tun=userspace-networking --state=/content/ts.state >/content/tailscaled.log 2>&1 &
sleep 3
tailscale up --auth-key="$TSKEY" --hostname=colab-policy
echo "tailnet ip: $(tailscale ip -4)"

echo "=== [2/5] lerobot v0.6.0 [molmoact2,async] ==="
cd /content
[ -d lerobot ] || git clone --depth 1 --branch v0.6.0 https://github.com/huggingface/lerobot
cd lerobot
pip install -q -e ".[molmoact2,async]"

echo "=== [3/5] async whitelist patch (molmoact2 not upstream-whitelisted) ==="
sed -i 's/SUPPORTED_POLICIES = \["molmoact2", /SUPPORTED_POLICIES = \[/' src/lerobot/async_inference/constants.py  # idempotence
sed -i 's/SUPPORTED_POLICIES = \[/SUPPORTED_POLICIES = ["molmoact2", /' src/lerobot/async_inference/constants.py
grep -n "SUPPORTED_POLICIES" src/lerobot/async_inference/constants.py

echo "=== [4/5] checkpoint snapshot -> bf16 (fp32 default won't fit an L4) ==="
hf download lerobot/MolmoAct2-SO100_101-LeRobot --local-dir /content/molmoact2_so101 >/dev/null
python - <<'EOF'
import json
p = "/content/molmoact2_so101/config.json"
c = json.load(open(p)); c["model_dtype"] = "bfloat16"
json.dump(c, open(p, "w"), indent=2)
print("model_dtype ->", c["model_dtype"])
EOF

echo "=== [5/5] policy server :8080 (blocking cell = keep-alive) ==="
echo "client should use: --pretrained_name_or_path=/content/molmoact2_so101 --server_address=$(tailscale ip -4):8080"
python -m lerobot.async_inference.policy_server --host=0.0.0.0 --port=8080
