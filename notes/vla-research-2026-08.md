# VLA research sweep — 2026-08-12

Three-agent web/GitHub sweep: SmolVLA deep-dive, full VLA landscape (Mac+Colab
constraints), Google On-Device 2 program. Dense reference — commands and links.

## Verdict in one line

Fine-tune SmolVLA on 50 fresh demos (only full Mac-fit, ~4h Colab A100, recipe
fully de-risked) · try MolmoAct2 zero-shot on a rented GPU (the ONLY zero-shot
SO-101 checkpoint in existence) · apply to Google On-Device 2 (SO-101 is
literally in their model card benchmark) · our lerobot 0.6.0 pin IS the current
latest release — no upgrade dilemma.

## SmolVLA facts that change how we work

- **Zero-shot is officially a dead end**: SmolVLA author (fracapuano,
  lerobot#2221): "no models on the Hub (aside from pi05) are intended for
  zero-shot." Nobody has ever reported a zero-shot grasp.
- **Our zero-shot run had a real bug on top**: `smolvla_base` processor stores
  norm stats under per-dataset keys (`so100.buffer.action.mean`), lerobot 0.6.0
  silently skips them → rollout ran with NO state norm / NO action de-norm.
  Open issues #1763, #2374 (the latter = macOS+MPS+SO-101, our exact setup).
- **Fine-tune recipe (don't deviate)**: 50 eps (25 is proven insufficient —
  HF's own words + Henry Hu 0% grasp at 25), batch 64, 20k steps ≈ 4h A100,
  keep baked-in defaults (lr 1e-4, freeze_vision_encoder, train_expert_only).
  ⚠ On 0.6.0 NEVER set `train_expert_only=false` (buggy until 0.6.1).
- Cameras: camera1=top/front, camera2=wrist (pretraining convention);
  or skip rename entirely and keep own keys consistent train↔rollout.
  Task string: verb-first, ≤30 chars ("Pick up the white cube"), EXACT same
  string at rollout. Images auto resize-pad to 512².
- Official Colab: huggingface/notebooks/lerobot/training-smolvla.ipynb
- Realistic expectation: 60–80% (ggando's 100% was one lucky 5/5 night;
  ACT was 80% on same data). On HARD multi-step tasks SmolVLA ≈ ACT
  (SO-101 VLA benchmark, arXiv 2606.08881: 32.5% vs 33.75%).
- Community SO-101 checkpoints on Hub: all env-specific + mostly old-format
  (pre-processor, need buggy migration #2701). Not worth it.
- `lerobot-doctor` (jashshah999/lerobot-doctor): `gate --policy smolvla`
  validates dataset; `score` flags bad episodes. Use before training.

## The landscape (ranked for us)

1. **SmolVLA 450M** — only VLA officially exercised on Apple Silicon (async
   docs use `policy_device=mps`, ~2GB). RTC (`--inference.type=rtc`) is the
   low-power mitigation. Do first.
2. **MolmoAct2 (Ai2)** — `lerobot/MolmoAct2-SO100_101-LeRobot`: ready-made
   SO-100/101 checkpoint, zero-shot, joint-calibration correction baked into
   processor (solves our degree-zero wart). Franka zero-shot 87–100%; SO-101
   numbers unpublished. Needs NVIDIA (12.1GiB bf16) → rent GPU $0.3–0.5/hr,
   serve via lerobot async `policy_server`, Mac `robot_client` over gRPC.
   Cheapest way to touch a foundation-grade policy on our arm.
3. **π0.5 (pi05, 3.3B)** — SO-101 benchmark king (56.25% avg hard tasks, 95%
   pen transfer, best failure recovery). Only Hub model INTENDED for zero-shot.
   Fine-tune sized for 80GB GPU (A100-40GB tight w/ expert-only + grad-ckpt +
   bs≤16). Needs q01/q99 stats (`lerobot-edit-dataset recompute_stats`) +
   gated paligemma license. Mac inference: no. Remote-serve only.
4. **EVO1 0.77B** (new in 0.6.0) — small-model dark horse, no SO-101 evidence
   yet. One-Colab-run experiment someday.
5. **X-VLA 0.9B** — lerobot-native, authors' benchmark built ON SO-101,
   phase-II adapts just 9M params. MPS untried. Watch.
- **Skip**: OpenVLA (no lerobot port, wrong action space), Octo/RDT/SpatialVLA
  (superseded), GR00T local (N1.5 orphaned — needs lerobot 0.5.1; N1.7 is
  cuda-only, π0.5 dominates that slot), world-model policies (24–32GB CUDA).
- **Remote inference pattern**: `python -m lerobot.async_inference.policy_server`
  on GPU box, `robot_client` on Mac streams obs/receives chunks (gRPC,
  chunk_size_threshold≈0.5). Works with every lerobot policy. Colab-as-server
  needs ngrok/tailscale (nobody's published it); rented GPU with real IP saner.
  Known wart: cuda-server/cpu-client tensor mismatches (#2137, #2244).
- **Phosphobot** (phospho-app): managed train+deploy for ACT/SmolVLA/π0.5/GR00T
  on SO-101 — shortcut if DIY fatigue hits.

## Google On-Device 2 (trusted tester)

- Launched 2026-07-30 with Gemini Robotics 2 family. **SO-101 is one of three
  platforms in the model card's fast-adaptation eval: 53.3% (v1: 6.7%)** —
  our application hook.
- Access = safari-sdk (`pip install safari-sdk`, ≥2.4.1) + API key unlocking
  the `flywheel` CLI: upload_data → train (GOOGLE'S cloud) → download ckpt →
  serve. Not open weights. Ships a LeRobot dataset converter. v2 adapts with
  "typically fewer than 200 examples."
- **Serving = Linux + NVIDIA** (Jetson AGX Orin class demoed). No Mac path.
  Colab bring-up plausible; Jetson Orin (~$700+) for real deploy.
- No hobbyist acceptance reports in 14 months of program. Apply anyway (free):
  category "AI Software", robot type Research Arm, models: On-Device + ER.
  Pitch: replicate their own SO-101 benchmark independently + existing LeRobot
  datasets + deployed teleop platform (crowdsourced demos = their flywheel).
  Form: https://docs.google.com/forms/d/1sM5GqcVMWv-KmKY3TOMpVtQ-lDFeAftQ-d9xQn92jCE/viewform
- **Waitlist-free Google ceiling**: ER 2 outputs points/boxes/**2D trajectory
  waypoints** (unused by us so far)/JSON — never actions. Our key also has
  `gemini-robotics-er-2-streaming-preview` (bidiGenerateContent / Live API):
  voice + continuous video + tool calls. Reference impl:
  github.com/google-gemini/robotics-samples (`live-api/` Physical Agent
  Server — FastAPI, tool dispatch, they wired Spot).
- `gemini-robotics-er-1.6-preview` deprecates end of Aug 2026 (we're on 2).

## Sequence locked in

1. Google form (5 min, free option).
2. 50 demos → SmolVLA fine-tune → A/B vs ACT (the queued plan, now de-risked).
3. ER 2 agent loop over our scripted primitives (tool schemas are the stable
   seam — later the tool becomes "run the fine-tuned policy").
4. MolmoAct2 zero-shot on rented GPU (weekend experiment).
5. π0.5 remote if we want benchmark-best.

## Watchlist addendum (2026-08-13)

- **Flex-π** (flex-pi.github.io, arXiv 2608.10860, UW/TRI/Ai2-adjacent): 6B
  multi-stream world-action model (future RGB + 3D pointmaps + DINO semantics
  + actions; cross-modality forcing). Claims 2.3× strongest baseline on
  bimanual YAM, beats π0.5, strong at 50 demos/task. Status: repo placeholder,
  code+checkpoints "ready soon", no SO-101/lerobot support, RTX 5090-class.
  RELEVANCE: our 50-demo dataset feeds it if ported; our daemon+remote-GPU
  topology runs 6B-class models already. Watch github.com/geyan21/flex-pi.

## Chess roadmap: two tracks (2026-08-18, from ChatGPT Isaac-sim convo review)

Source: ChatGPT plan (LeRobot -> LeIsaac -> Isaac Lab -> Isaac Sim, SO-101
chess env, Runpod 4090 ~$0.34/h + $14/mo storage ~= $36/mo). Assessment
against lab evidence:

**Key insight: the chess decomposition ChatGPT proposes (engine -> "e2e4" ->
manipulation task) IS our v2 architecture** — ER 2 orchestrator + policy +
camera verification, already running. Swap mission source to python-chess and
the architecture is the chess robot.

**Track A — real-world precision (PRIORITY, unchanged):**
1. 50 real teleop demos (wall setup, data rules).
2. Fine-tune SmolVLA (baseline) + MolmoAct2-LoRA (upside), A/B.
3. Precise placement proven -> **real mini-chess**: 2x2 squares, 2 pieces,
   python-chess -> orchestrator run_task missions. Shortest path to a real
   legal chess move. No Isaac needed.

**Track B — sim (parallel, learning + scale):**
- The 7-day LeIsaac sprint as ChatGPT outlines (day 1 install + LiftCube,
  day 2 leader->sim-follower teleop, day 3 EE control, day 4-5 chess env +
  scripted e2e4, day 6 teleop demos, day 7 ACT train in sim).
- GOAL REFRAMED: not sim2real chess transfer, but (1) learn the Isaac stack,
  (2) demo-factory (real leader -> sim follower = unlimited randomized
  demonstrations), (3) board-geometry testbed (34cm board vs reach — measure
  in sim before buying/mounting anything), (4) two-arm chess seed.
- Sim2real caution stands: ggando pixel-RL total-failure + our viewpoint-shift
  0.80->0.13 measurement. Sim-trained policies are sim achievements until
  proven on the real arm. Imitation+domain-randomization is the credible
  variant, but Track A carries the real-world burden.
- Infra: Runpod 4090 community + 200GB network volume (Isaac needs RTX-class;
  Colab can't). Our tailnet/remote-GPU discipline carries over.
- ⚠ Before install: verify LeIsaac's required lerobot version vs our 0.6.0
  pin (version-match lever applies to sim too).

Convergence: sim demos augment real demos for fine-tunes; sim chess env
becomes the rehearsal space for full-board play.
