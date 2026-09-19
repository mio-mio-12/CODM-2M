# Spawn sidecar: codm.spawns/1

CODM-2M-v007 automatically writes `spawns.json` beside C2M/GLB exports. It reads StartSpot components from exact matching gameplay scene families, separately from the visual scene. Visual suffixes Atlases/Final/HQ/New are removed for association; named variants such as Halloween and CW are retained. No base-map fallback is performed when a variant has no match. This matching covers the tested installation conventions, not every possible map layout.

The root has `schema`, `generator`, `visualScenes`, `status`, `complete`, `spawnCount`, `sets`, `matchedScenes`, `sourceBundles`, and `errors`. Status is `found`, `not_found`, or `partial`. `complete` concerns decoding of matching scenes, not exhaustive discovery of runtime spawns. A `not_found` result is not proof that the game has no spawn positions.

Each set has source `scene`, `mapFamily`, `mode` (original Main_TDM etc. suffix), numeric `modeTypes` from ModeDetail, and `spawns`. Sets without spawn records are omitted; inspected scene identities remain in `matchedScenes`. Never combine mode sets automatically. The UI reports a total across sets, not the number active in one match.

Each spawn has:

- `id`: serialized file plus path ID; `uid`: original game UID; `name`: original object name.
- `position`, `forward`, `up`: right-handed Z-up **inches** for position, unitless normalized facing/up directions. These align with the C2M visual/collision convention. Multiply positions by 2.54 and the user scale exactly once for Cadence centimetres.
- `glbPositionMetres`, `glbForward`, `glbUp`: alternative right-handed Y-up GLB coordinates. Apply Cadence's ordinary GLB-to-scene conversion, not the C2M conversion. Choose one representation, not both.
- `enabled`, `hierarchyActive`, `available`, `initialSpawn`: source flags. Retain all records; a consumer should normally filter the first three before selecting a playable spawn. Use `initialSpawn` for match-start selection when appropriate, not as a blanket filter for respawns.
- `camp`, `group`, `aiOnly`: raw source team/group metadata. Do not invent faction labels or assume a fixed meaning for camp 0 without a mode policy.
- `sourceProperties`: original StartSpot properties, including tutorial, map area, objective, stage and route fields.

Full parent transforms are composed before conversion. Positions and orientations must be finite. Coordinate conversions from Unity metres are C2M `(-x,-z,y)/0.0254` and GLB `(-x,y,z)`; direction vectors use the same axis changes without unit scaling.

The map report and C2MX META contain `spawnFile`, `spawnCount`, `spawnStatus` and `spawnComplete`. GLB-only consumers locate `spawns.json` in the same export directory. Spawn decode failures produce a partial sidecar and visible status without dropping the map geometry. CLI map export returns 2 on partial spawn extraction.

Cadence integration: offer mode selection, load the chosen set, preserve flags/team metadata, display markers/facing, and validate spawn clearance against authored collision before use. The file supplies authored candidate points, not CODM's runtime spawn scoring or enemy-distance logic. Bot navigation/cover/camp markers are not included in this spawn-only feature.

Validated data: Standoff Halloween 342 records in ten mode sets (TDM 41, SD 12, HP 40); SBNC 136 in five sets; Crash 1,368 in 43 sets. All three extractions completed without errors. No inspected StartSpot is marked AI-only. These are records per mode, not unique physical coordinates.
