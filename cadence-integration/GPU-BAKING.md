# CODM-2M-v007 baked exports

No new Cadence shader or file-format support is needed for the GPU backend. It writes the same baked color, tangent-normal and metallic/roughness PNG roles, GLB PBR textures and C2M/C2MX data as the CPU backend.

`vertexBlendBake.backend` on baked surface/material metadata is `gpu`, `cpu`, or `reused` (internal recovery). The `baking` report section has the requested backend, device, page counts, fallback reason and times. Baked texture pixels may differ by normal GPU floating-point rounding; tested SBNC surfaces differed by at most one 8-bit channel step.

GLB material indices are local to its own material table. Unreferenced source materials are omitted from GLB; C2M and source-material records retain their own tables. Never use a material index from one format to index another format's table.

Original editable layer recipes and UV/vertex-weight NPZ files remain alongside the export. GPU baking does not change separate collision, spawn, gameplay-volume or tactical-marker conventions. Continue using C2MX-FORMAT.md, IMPLEMENT-IN-CADENCE.md, SPAWNS.md and GAMEPLAY.md.
