# Gaussian Splatting for the SO-101 lab — research memo

- **Date:** 2026-08-18
- **Status:** researched; deferred as a bounded Track B experiment
- **Source prompt:** review *3D Gaussian Splatting for Real-Time Radiance Field
  Rendering* and related work, then decide what is useful for the chess robot.

## Verdict in one line

Use a Gaussian splat as the **photorealistic visual layer of the existing
simulator**, while MuJoCo/Isaac meshes, the URDF, and explicit collision bodies
continue to own geometry and physics. Do not put raw splats in the control loop
or let this delay the 50-real-demo Track A baseline.

The best first experiment is a metric-aligned splat of the static workspace,
rendered behind the simulated SO-101 and chess assets. Compare it against both
plain MuJoCo and a much cheaper real-photo background before investing further.

## Why this is unusually feasible for this repo

- The lab already has an offscreen MuJoCo camera renderer in
  `chess_system/mujoco/render_scene.py` and exact chess assets/colliders.
- Both policy cameras are known: fixed C922 overhead and moving wrist camera,
  640x480 at 30 FPS.
- `chess_system/config/chess_geometry.json` defines a metric robot-base frame,
  four 20 mm fiducials, and their exact centers. These can resolve the arbitrary
  scale and frame of a monocular COLMAP/3DGS reconstruction.
- A 24 GB RTX 4090 and persistent Runpod volume are already provisioned for the
  Isaac Track B work.
- The current roadmap already reserves sim for learning, demo generation, and
  rehearsal while real data remains responsible for real-world reliability.

## What the original paper contributed

Paper: [3D Gaussian Splatting for Real-Time Radiance Field Rendering](https://arxiv.org/abs/2308.04079),
Kerbl et al., SIGGRAPH 2023. [Original project page](https://repo-sam.inria.fr/fungraph/3d-gaussian-splatting/).

### Input and representation

The method takes overlapping images of a **static** scene plus camera poses and
a sparse point cloud from Structure-from-Motion (normally COLMAP). Each point
becomes an explicit anisotropic 3D Gaussian with:

- center/mean `mu`;
- rotation and 3-axis scale, which form its covariance;
- opacity;
- spherical-harmonic coefficients for view-dependent color.

The representation is explicit and unstructured: there is no MLP that must be
queried repeatedly along every camera ray.

### Optimization

Training repeatedly renders a known camera view and compares it with its real
image using an L1 plus D-SSIM loss. It jointly optimizes Gaussian positions,
scales, rotations, opacity, and color. Adaptive density control:

- clones small Gaussians in under-reconstructed regions;
- splits overly large Gaussians;
- prunes nearly transparent or otherwise ineffective Gaussians.

The paper reports roughly 1–5 million Gaussians for its real scenes. Its
high-quality setting took about 51 minutes on the reference system.

### Rendering

The CUDA renderer projects the 3D ellipsoids to 2D, bins them into screen
tiles, sorts them by depth, and alpha-composites them. This produced the paper's
first high-quality radiance-field result capable of at least 30 FPS at 1080p.

### What it is good at

- Photorealistic novel-view synthesis.
- Fast differentiable rendering and comparatively fast reconstruction.
- Explicit primitives that can be selected, transformed, segmented, or bound
  to other structures.
- Preserving the real workspace's textures, clutter, cables, shadows, and
  camera-specific appearance better than hand-authored simulator assets.

### What it is not

- A trustworthy watertight surface or collision model.
- Metric without an external scale reference.
- A physics or material model.
- Naturally dynamic: the original method assumes the scene does not move.
- Robust outside the region and camera scales represented by training images.

The original paper itself reports artifacts in poorly observed regions,
elongated/splotchy Gaussians, popping, and depth-order changes. Its photometric
objective can reproduce training images while placing geometry incorrectly.
Lighting, reflections, and shadows are generally baked into appearance rather
than responding correctly when simulated objects move.

## Related-paper map

### More stable static rendering

- [Mip-Splatting](https://arxiv.org/abs/2311.16493) adds 3D smoothing and a 2D
  mip filter to reduce erosion, dilation, and aliasing when render scale or
  camera distance changes. This is relevant to the moving wrist camera.
- [Scaffold-GS](https://arxiv.org/abs/2312.00109) organizes view-adaptive
  Gaussians around anchors, reducing redundancy and improving difficult view
  changes, textureless areas, reflections, and model compactness.

These improve interpolation and scale changes; neither can invent genuinely
unobserved sides of the workspace. Capture coverage remains the first lever.

### Geometry and mesh extraction

- [2D Gaussian Splatting](https://arxiv.org/abs/2403.17888) replaces volumetric
  ellipsoids with oriented Gaussian disks and adds depth-distortion/normal
  consistency losses for more view-consistent surfaces and mesh extraction.
- [SuGaR](https://imagine.enpc.fr/~guedona/sugar/) regularizes Gaussians toward
  surfaces, extracts a Poisson mesh, and can bind Gaussians to mesh triangles
  for editing, rigging, animation, and relighting.

These are fallback tools for unknown scene geometry. For the board, pieces,
tool extensions, and robot, our measured CAD and simple conservative collision
geometry are more reliable than recovered geometry.

### Online mapping and camera tracking

- [SplaTAM](https://arxiv.org/abs/2312.02126) performs online dense RGB-D SLAM
  with a Gaussian map.
- [Gaussian Splatting SLAM](https://openaccess.thecvf.com/content/CVPR2024/html/Matsuki_Gaussian_Splatting_SLAM_CVPR_2024_paper.html)
  jointly maps and tracks a monocular camera against Gaussians.

Useful for a roaming robot, but unnecessary for the first tabletop twin. A
careful offline phone capture is simpler, higher quality, and easier to align.

### Semantics and open-vocabulary manipulation

- [LangSplat](https://arxiv.org/abs/2312.16084) distills hierarchical language
  features into a Gaussian scene for fast open-vocabulary 3D queries.
- [GaussianGrasper](https://arxiv.org/abs/2403.09637) combines RGB-D views,
  language features, reconstructed geometry, and a grasp model for
  language-selected collision-free grasps.
- [Splat-MOVER](https://arxiv.org/abs/2405.04378) adds semantic and grasp
  affordance features, plus real-time scene editing after objects move.

These matter for open-world manipulation. Chess has known object identities,
known legal state, exact squares, and purpose-built grasp geometry, so this is
not where we should spend effort now.

### Dynamic Gaussians and learned world models

- [Dynamic 3D Gaussians](https://arxiv.org/abs/2308.09713) tracks persistent
  Gaussians through time with local-rigidity constraints.
- [ManiGaussian](https://arxiv.org/abs/2403.08321) learns scene dynamics through
  future Gaussian reconstruction for language-conditioned RLBench tasks.
- [Physically Embodied Gaussian Splatting](https://arxiv.org/abs/2406.10788)
  bonds visual Gaussians to particles, predicts physical motion, and corrects
  it from camera observations.
- [Gaussian World Model](https://arxiv.org/abs/2508.17600) uses a 3D VAE and
  diffusion transformer to predict future Gaussian scenes under robot actions.

These are research directions, not drop-in LeRobot components. They require
substantial aligned data and model work and do not address the current
precision bottleneck better than the existing ER-2 + policy + verification
architecture.

### Gaussian-splat robot simulation

- [SplatSim](https://arxiv.org/abs/2409.10161), ICRA 2025, uses splats as the
  visual renderer over an existing simulator and reports 86.25% average
  zero-shot sim-to-real success on its own RGB manipulation tasks versus 97.5%
  for policies trained on real images. This is evidence for the direction, not
  a performance promise for an SO-101 or chess.
- [RoboGSim](https://arxiv.org/abs/2411.11839) combines a Gaussian
  reconstructor, digital-twin builder, scene composer, and physics-backed
  interactive engine for simulated data generation and policy evaluation.
- [Splatting Physical Scenes](https://arxiv.org/abs/2506.04120) jointly refines
  splat appearance, explicit physics-ready object meshes, camera parameters,
  robot poses, and physical parameters using differentiable rendering and
  MuJoCo/MJX physics.
- [GSWorld](https://arxiv.org/abs/2510.20813), ICRA 2026, uses Gaussian-on-Mesh
  assets plus robot URDFs and physics. It explores sim-to-real imitation,
  closed-loop DAgger corrections, policy benchmarking, virtual teleoperation,
  and visual RL.
- [RoboSimGS](https://github.com/Maxwell-Zhao/RoboSimGS) is especially relevant
  because its released pipeline uses Nerfstudio for 3DGS backgrounds, mesh
  objects for physics, Genesis for simulation, and LeRobot for deployment.
  The repository is still incomplete around automatic camera-pose alignment.

The important convergence is a **hybrid representation**:

1. Gaussians own photorealistic appearance.
2. Meshes/URDFs own kinematics, contact, collision, and physics.
3. A calibrated rigid transform keeps the two worlds registered.

That is the architecture to copy, not any one paper's full stack.

## Recommended architecture for this lab

```text
phone video -> COLMAP poses -> Nerfstudio Splatfacto -> static workspace PLY
                                      |
                                      v
metric board fiducials -> similarity transform -> SO-101 base/world frame
                                      |
                                      v
              Gaussian background renderer + MuJoCo/Isaac foreground
                                      |
                                      v
                 LeRobot-format RGB observations + simulator actions
```

### Ownership boundaries

- **Static room/table/background:** Gaussian splat visual layer.
- **SO-101, gripper extensions, board, pieces, bins:** existing CAD/URDF/MJCF
  visuals and explicit physics bodies.
- **Camera motion:** simulator camera poses transformed into the splat frame.
- **Collision:** MuJoCo/PhysX meshes only; never raw Gaussian opacity.
- **State and actions:** unchanged LeRobot schema so datasets remain comparable.

## Bounded future spike

Do this only after, or genuinely in parallel with, the 50-real-demo baseline.
The spike should answer whether 3DGS adds measurable value over a simple real
background plate.

### Phase 0 — calibrate the cameras

1. Calibrate C922 and wrist-camera intrinsics with a checkerboard.
2. Recover the fixed overhead camera extrinsic from the board fiducials.
3. For the wrist camera, collect multiple arm poses observing the fiducials and
   solve the camera-to-gripper hand-eye transform using robot FK.
4. Store versioned intrinsics/extrinsics next to the existing board and wrist
   calibration, rather than baking guessed camera poses into MJCF.

This calibration is useful even if the splat experiment fails.

### Phase 1 — establish the cheap visual baselines

Render the same known chess pose three ways:

1. current plain MuJoCo;
2. MuJoCo robot/pieces over a clean real 2D background photograph;
3. MuJoCo robot/pieces over the 3D Gaussian workspace.

The overhead camera is fixed, so a 2D plate may be sufficient there. The
unique value of 3DGS should appear in wrist-camera motion, novel viewpoints,
or camera randomization.

### Phase 2 — capture one static workspace

Capture protocol:

- Remove or mask the robot; keep the workspace static.
- Remove movable chess pieces for the first scan. Keep the metric board and
  fiducials visible.
- Lock focus, exposure, white balance, and lighting.
- Prefer diffuse light; avoid hard moving reflections and cast shadows.
- Record a slow 1–2 minute phone video with high frame overlap.
- Make multiple orbits at different heights and distances.
- Include close, low angles covering the entire reachable wrist-camera view
  cone, not just attractive human-height views.
- Record a separate held-out path for evaluation.

The first pass should use Nerfstudio's maintained `splatfacto`/`gsplat` stack,
not the older INRIA research environment:

```bash
ns-process-data video \
  --data workspace.mov \
  --output-dir workspace-data

ns-train splatfacto --data workspace-data

ns-export gaussian-splat \
  --load-config outputs/.../config.yml \
  --output-dir exports/workspace
```

Nerfstudio docs:
[custom data](https://docs.nerf.studio/quickstart/custom_dataset.html) and
[Splatfacto/export](https://github.com/nerfstudio-project/nerfstudio/blob/main/docs/nerfology/methods/splat.md).
The documented default Splatfacto configuration is about 6 GB VRAM and the
larger version about 12 GB, both comfortable on the existing 24 GB 4090.

### Phase 3 — metric alignment

COLMAP reconstruction is only defined up to a similarity transform. Detect the
four known board fiducials in registered capture images, lift their locations
into the reconstruction, and solve scale + rotation + translation into the
`chess_geometry.json` robot-base frame.

Acceptance checks:

- reconstructed 204 mm board carrier dimensions match the manifest;
- board plane aligns with `nominal_top_z`;
- all four fiducial centers are within a documented reprojection/3D tolerance;
- the real overhead and wrist camera poses render the expected board corners;
- the transform is serialized and reproducible, not manually eyeballed.

Manual CloudCompare alignment is acceptable only as an initial visualization,
not as the final repeatable pipeline.

### Phase 4 — MuJoCo integration first

[MuGS](https://github.com/Renforce-Dynamics/MuGS) is the shortest current
engineering route. It is an MIT-licensed, early-stage implementation that:

- accepts standard Nerfstudio/COLMAP Gaussian PLY files;
- extracts moving camera parameters from MuJoCo;
- renders a 3DGS background with `gsplat`;
- renders the robot and interactive objects in MuJoCo;
- composites them with simulator segmentation masks;
- exposes a standalone `GaussianSensor` API.

Wrap the rendering point in `chess_system/mujoco/render_scene.py` first. Do not
fork the physics backend or change chess-state logic. Pin an exact MuGS/gsplat
revision if the proof works: MuGS is a useful implementation shortcut but does
not yet have the maturity of the peer-reviewed methods above.

Known visual limitations to test explicitly:

- correct foreground/background depth ordering;
- robot/object shadows absent from the baked splat;
- foreground color temperature versus real background;
- black regions/floaters outside the capture-camera hull;
- wrist views very close to the board;
- anti-aliasing when rendering at 640x480 versus capture resolution.

### Phase 5 — Isaac/NuRec only after the proof

Current Isaac Sim/NuRec can render Gaussian-splat particle fields in OpenUSD.
NVIDIA's documented robotics workflow pairs the visual Gaussian volume with a
separate hidden GLB collider, exactly matching the hybrid conclusion above:

- [NuRec rendering utilities](https://docs.isaacsim.omniverse.nvidia.com/latest/assets/nurec_utils.html)
- [Isaac Sim Gaussian scene + collider workflow](https://developer.nvidia.com/blog/simulate-robotic-environments-faster-with-nvidia-isaac-sim-and-world-labs-marble/)

This is attractive for the planned Isaac Track B and synthetic-data pipeline,
but the APIs are newer, CUDA/single-GPU constrained, and heavier to debug.
Validate the representation in MuJoCo before coupling it to the Isaac bootstrap.

## Policy experiment

Keep trajectories, policy settings, camera keys, and task text identical. Train
and evaluate:

| Arm | Training observations | Purpose |
|---|---|---|
| A | 50 real demonstrations only | Required real baseline |
| B | Real + ordinary MuJoCo demos | Does simulation help at all? |
| C | Real + 2D-real-background sim demos | Cheap appearance baseline |
| D | Real + 3DGS-background sim demos | Incremental value of novel-view realism |

Do not claim success from attractive renderings or image metrics. The primary
test is repeated real-hardware task success.

Track at least:

- grasp success;
- verified lift success;
- placement error in millimeters;
- full task success with no retries;
- robustness to small overhead-camera shifts;
- wrist-camera occlusion/fine-servo failures;
- correlation between simulated and real policy failures;
- held-out PSNR/SSIM/LPIPS only as secondary renderer diagnostics.

Use the same evaluation checklist, seeds where possible, and a meaningful
number of physical trials. A paper's success percentage on a UR5/Franka/xArm
task is not evidence for the SO-101 until reproduced here.

## Go/no-go gates

### Continue beyond the spike only if

- held-out overhead and wrist views are stable throughout the actual reachable
  camera envelope;
- metric alignment is repeatable after retraining;
- the Gaussian render adds useful novel-view behavior over the 2D plate;
- throughput comfortably exceeds the 30 Hz observation requirement;
- real-policy results improve beyond run-to-run noise, or sim failures become
  meaningfully predictive of real failures.

### Stop or simplify if

- the fixed-camera 2D plate performs equally well;
- missing-view artifacts dominate wrist images;
- camera/scene alignment requires recurring manual adjustment;
- splat-specific dependency work delays the real-data baseline;
- rendering improves visually but real success does not improve.

Stopping with a calibrated camera model and a clean 2D compositing pipeline is
still a useful outcome.

## Explicit non-goals

- Do not replace Track A or the initial 50 real demonstrations.
- Do not use raw Gaussian opacity as collision geometry.
- Do not scan the tiny chess pieces instead of using their existing CAD.
- Do not train ManiGaussian/GWM/4DGS as the first experiment.
- Do not add SLAM to a workspace that can be scanned offline.
- Do not add language features for already-known chess identities and squares.
- Do not treat photorealism as proof of correct physics or sim-to-real transfer.

## Future task checklist

- [ ] Finish 50-real-demo baseline first or assign this as genuinely parallel
      Track B work.
- [ ] Calibrate camera intrinsics and overhead/wrist extrinsics.
- [ ] Capture clean 2D overhead background baseline.
- [ ] Capture static workspace train/eval videos with fiducials.
- [ ] Add a reproducible Nerfstudio job on the Runpod volume.
- [ ] Export and archive `workspace.ply`, COLMAP data, config, and commit hashes.
- [ ] Implement fiducial-driven similarity alignment into robot-base frame.
- [ ] Produce plain/2D/3D matched-view comparison sheet.
- [ ] Prototype MuGS behind `chess_system/mujoco/render_scene.py`.
- [ ] Verify 30 Hz overhead and moving-wrist rendering.
- [ ] Generate a small LeRobot-format simulation dataset.
- [ ] Run the controlled real-policy A/B before any Isaac/NuRec port.
- [ ] If useful, port the proven assets into Isaac Sim/NuRec and attach explicit
      collider meshes.

## Final decision

This is a **green-lighted but deferred, bounded experiment**, not a new core
architecture. Its most credible payoff is closing part of the visual sim-real
gap for the wrist camera and making simulated chess rehearsals/data more useful.
Its least credible uses here are collision recovery, open-vocabulary grasping,
or replacing real demonstrations.

The first durable deliverable should be:

1. one metric-aligned static `workspace.ply`;
2. one serialized GS-to-robot transform;
3. held-out renders at the real overhead and wrist poses;
4. a plain MuJoCo vs 2D plate vs 3DGS comparison;
5. a written go/no-go decision before more integration work.
