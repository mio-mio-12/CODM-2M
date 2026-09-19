# Gameplay sidecars - v008

`gameplay_volumes.json` (`codm.gameplay-volumes/1`) and `tactical_markers.json` (`codm.tactical-markers/1`) are optional sidecars beside the C2M/GLB. They contain no rendered surfaces and do not alter authored solid collision. The exporter supplies data; Cadence needs a reader and explicit runtime behavior for these components.

Both files contain generator, visualScenes, matchedScenes, sourceBundles, status (found/not_found/partial), complete, count, errors and sets. Each set has source scene, mapFamily, mode, raw modeTypes and items. Mode-specific sets must not be merged indiscriminately; LDBasic records are explicitly identified as shared-scene records. Only exact map-family matches or explicitly selected gameplay scenes are read. Visual quality suffixes are ignored, but Halloween/CW/etc. variants are retained. No unverified base-map substitution is made.

## Coordinates

Positions, local dimensions and matrix translations are C2M right-handed Z-up inches. Matrices are column-major; basis vectors retain scale and reflection. Forward/up are normalized directions. Convert positions to Cadence centimetres by 2.54 and user scale exactly once. Corresponding `glbPositionMetres`, `glbForward`, `glbUp`, and `glbMatrixMetres` fields are right-handed Y-up metres for the GLB pipeline. Do not mix the two conventions.

Each item includes id, original uid/name/kind, component enabled state, hierarchyActive, pose and sourceProperties. sourceProperties remain original Unity property values and serialized references; their numbers have NOT all been converted to the sidecar coordinate system. Use the explicit normalized fields for transforms and shapes. Preserve unknown enums and source properties rather than inventing meanings.

## Gameplay volumes

Supported components: DeathZoneVolume, ClimbUpTriggerVolume, CrouchVolume and DoorAssistantVolume. Their sourceProperties retain death/HUD delays, camp/filter flags, climb heights/angle/distance, crouch speed and door-assist angle/force where present.

`shapes` contains colliders attached to the component's GameObject plus its explicitly referenced collider list, deduplicated by source ID. The reader does not guess a volume from arbitrary nearby or descendant meshes. Every shape uses its own GameObject transform.

- BoxCollider: local center, full size, matrix and eight already-transformed worldCorners. GLB alternatives are glbCenterMetres, glbSizeMetres and glbWorldCornersMetres. Transform center Â± size/2 with matrix, OR use worldCorners directly; never do both. Reflected/scaled/rotated boxes are preserved.
- SphereCollider: local radius/center, matrix, `scalePolicy=unity_max_axis`.
- CapsuleCollider: local radius, total height, center, axis, matrix and `scalePolicy=unity_axis_height_max_perpendicular_radius`. C2M axis order is X/Y/Z in Z-up space; glbAxis retains GLB axis order. Clamp runtime capsule height against its diameter as required by the engine.
- Enabled, hierarchyActive and original trigger flag are retained per shape. These are gameplay detection volumes, not automatically solid barriers.
- Unknown collider shapes and missing collider associations set shapeStatus to partial/missing and record errors. They are not silently converted into boxes. Primitive extents and transformed coordinates are validated. Only supported shapes are marked complete.

Runtime integration should choose the correct set, filter enabled/hierarchyActive items/shapes, visualize optionally, then implement volume entry/exit rules separately. Reading DeathZoneVolume does not itself implement CODM's death timing or local-player rules.

## Tactical markers

Kinds are BOTNaviSpot, CampSpot and CoverSpot. They preserve world pose and original parameters:

- BOTNaviSpot: spot type, area, camp, group and index.
- CampSpot: stance, weapon priority, extra aim rotation, camping duration and camp.
- CoverSpot: crouch cover, left/right/top peek flags, wall distance, margins and neighboring-cover references.

Non-null direct object references are resolved to stable serialized-file:path-ID strings in `links`; raw references remain in sourceProperties. A link may point outside the selected subset. Preserve and report unresolved links; do not create inferred navigation edges. BOTNaviSpot is not a decoded navmesh polygon/adjacency graph.

These markers can support authoring overlays and future bot logic. They do not supply a complete bot controller, pathfinder or cover-selection system.

## Validation

SBNC: 39 gameplay volumes and 13 tactical markers. Crash across its mode scenes: 431 and 369. Standard Standoff: 187 and 34. All completed with zero extraction errors. These are serialized records across sets, not deduplicated physical positions.

Standoff Halloween: no exact matching volumes/tactical markers found; the output explicitly reports not_found. Its 342 spawn records remain available separately. Standard Standoff data is not silently assigned to Halloween.

The map report/C2MX META adds `gameplaySidecars` with file/count/status/complete per enabled sidecar and `gameplayComplete`. UI jobs and CLI exports report partial if these sidecars have extraction errors. Disabled options do not write the corresponding file.


## v008 additions

Gameplay volumes now include NavMeshModifierVolume and these objective components: DOMObjectiveVolume, HPObjectiveVolume, ControlObjectiveVolume, GFObjectiveVolume, BombPlacingPointVolume, BombInitTriggerVolume and SafeGuardTargetVolume.

Navigation modifiers use a BoxCollider-shaped geometry record synthesized from the authored m_Center/m_Size fields, not a physical collider. shapeSource is component_fields and solidCollision is false. Apply the shape transform once. areaId and affectedAgents retain authored numeric identifiers; do not assume area 17 means blocked. Cadence must map these IDs when rebuilding navigation. These are modifiers, not decoded navmesh polygons.

Objectives retain objectiveId, their mode scene and all sourceProperties. additionalTriggerIds lists directly referenced auxiliary triggers. Shapes include attached/explicit colliders and recursively referenced AdditionalTriggers/AdditionalTriggers_Dom, deduplicated by source ID and transformed using each collider's own transform. Do not merge objectives from different modes or create solid collision from these shapes. Capture speeds, timing and other unnormalized settings remain source units.

ClimbSpot is included in tactical_markers.json under Tactical markers. endpoints.startPoint/endPoint contain resolved world poses in both coordinate conventions, stable IDs and hierarchyActive. height is inches; glbHeightMetres is metres. climbType retains the source enum. endpointStatus is partial with an extraction error if a reference is missing. Endpoint poses are already world-space; do not multiply by the parent marker matrix again. A climb spot is a traversal link, not a solid volume. No traversal animation or AI behavior is implemented by export.
