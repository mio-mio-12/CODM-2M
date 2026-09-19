# CODM-2M-v007 zones and ladders

## Zone folders

zone.json uses schema codm.zone-export/1. Its cells and chunk bounds are source Unity X/Z metres for selection; they are not C2M-space positions. Each chunk record identifies a scene, selected layer, relative folder, status and output counts. Import the requested visual files from Complete chunks. Review Partial chunks and their report.json errors. Pending, Exporting, Error or Cancelled records must not be treated as finished.

GLB coordinates stay RH Y-up metres; C2M and collision.json stay RH Z-up inches. Every chunk already uses the original world coordinates. Do not center each chunk, apply tile offsets a second time, or infer placement from the folder number. Whole-chunk selection may extend beyond the requested cells. Deduplicate repeated source IDs if combining separate zone exports with overlapping coverage.

Read collision.json even when a chunk has no visual map file. Collision-only scenes are useful independent outputs. Do not assume selecting a grid region produces complete terrain or all runtime-instanced foliage. The manifest's scope states that these are streamed scene exports, not full runtime world assembly. Gameplay sidecars are not spatially filtered into zone folders in this release.

## Ladder gameplay volumes

The existing codm.gameplay-volumes/1 schema adds kinds LadderVolume and LadderEnterVolume. Both contain the existing position, forward, up, matrix, glbPositionMetres, glbMatrixMetres, enabled, hierarchyActive, sourceProperties and shapes fields. No solid collision or ladder movement code is implied by these trigger records.

LadderEnterVolume.targetLadderId is the stable source ID of its TargetLadderVolume reference, or null when no reference is assigned. Resolve within the matching map/mode data. Preserve unmatched targets as unresolved; do not guess the nearest ladder. In Highrise, the three entry triggers resolve to three exported LadderVolume records in LDBasic.

Source properties are kept in original game units and spelling. LadderVolume includes Speed, LadderStep, LadderButtomGap, LadderTopGap, HasHandrail, IsForbidDownToLadder and LadderCenterOffset where authored. LadderEnterVolume includes IsClimbEnter and IsCorssWindow. Only the normalized pose/shape fields have converted coordinate conventions; do not interpret raw sourceProperties distances as C2M inches. Collider shapes retain parent transforms and scaling.

These records describe source gameplay intent. Cadence must implement attachment, climbing, entry/exit handling, animation and movement itself. Check enabled/hierarchyActive and shapeStatus, and keep volume triggers separate from solid physics collision.
