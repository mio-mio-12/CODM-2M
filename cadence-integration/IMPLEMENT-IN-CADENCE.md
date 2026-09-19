# Integrate authored CODM collision into Cadence

This is an implementation handoff. The map compiler has not modified or rebuilt the active Cadence project.

Authoritative source inspected:
`<cadence-project>`

Read that project's current `AGENTS.md` and current source before editing; another active task is working there. Follow its version/build protocol when the user authorizes a Cadence build. Do not overwrite its current executable.

## Required change

`src/scene/C2MMap.cpp` currently derives `scene::glb::Map::collision` from visible world/prop surfaces in `emitGeometry`. For a C2MX map, load the independent `COLL` chunk instead. Keep old C2M behavior when no extension is present.

1. Before emitting geometry, use `C2mxReader.h` to inspect the footer and directory. Parse `META`, `COLL` and `NAVM` JSON using a bounded JSON parser. Validate schema versions, array sizes, finite numbers, index ranges, matrix length 16, positive shape extents and layer range. Reject a malformed extension; do not silently fall back.
2. Hold the authored collision data in a temporary structure until the whole chunk passes validation. If `META.collisionComplete=false`, keep visual preview available but present an explicit incomplete-collision status; require an intentional choice before using approximate physics.
3. With a valid complete `COLL`, suppress every visual-to-collision emission in `emitGeometry`, including both world object 0 and static/dynamic model instances. An empty authored list stays empty.
4. Convert non-trigger box and triangle-mesh records into `scene::glb::CollisionTriangle`. Use source surfaces and IDs for diagnostics. Build proper box faces, including top faces; transform positions correctly and derive normals from the final triangle edges. Invert winding for mirrored box transforms. Mesh records are already world-space and need only inches-to-centimetres conversion and the user's map scale.
5. Keep sphere/capsule records analytic if the query layer permits. Otherwise expose tessellation as an approximation with a controllable quality setting. Respect the explicit Unity scale policies; do not deform a sphere into an ellipsoid or scale capsule radius with its length axis. Convex MeshColliders require the hull step described in the format spec.
6. Set triangle bounds, walkability and blocking flags consistently with the existing movement system. A slope test alone is not a full navmesh. Do not accidentally mark triggers as floors or walls. Preserve source layer/physics material separately from cosmetic material names.
7. Once all geometry is loaded, call `map.buildCollisionIndex()` once. Choose/validate spawn against the new collision after the replacement. Never reuse a collision index built from the old render triangles.
8. Read `NAVM` status. King currently provides build settings only. Feed authored collision into Cadence's existing navigation generation when desired, label it generated, and keep the retained game settings/payload available. Do not toggle native-navigation success just because a NAVM chunk exists.

## Visual material overrides

The base C2M compatibility layer already recognizes ordinary, additive and multiply decal names/techsets. For more reliable behavior, apply `META.visualMaterials[matIdx]` while constructing each mesh in `emitGeometry`:

- Explicit `decal`, `decalMultiply`, `decalAdditive`, `alphaTest`, `forceAlpha`, cutoff and double-sided policy override name heuristics.
- Keep decals out of collision; honor depth bias and queue ordering; disable depth writes for blended decal passes. Render ordinary opaque surfaces first, alpha-tested surfaces next, then alpha, multiply and additive decal passes according to the renderer's established policy. Sort blended surfaces where needed.
- Use `color`, PBR factors and normal/metallic-roughness maps. The compiler's metallic texture uses glTF channels G=roughness, B=metallic. Set `gltfPbr=true` only for that representation, not a source CoD specular texture.
- Honor `alpha=MASK` and `cutoff` for CODM foliage, including `_STATIC_FOLIAGE`/TransparentCutout materials. Honor `unlit` for static screen artwork; do not add a white emission constant. For `blend=additive`, use native additive rendering with `textures.color` and source alpha. `glbColorTexture`/`glbColorFactor` are GLB-only approximations and must not replace the C2M additive texture. `staticFX` records effects whose animation was not baked.
- Resolve texture paths relative to the map directory and keep them within the package. The old C2M table references image stems so existing builds find `images/` automatically.
- Preserve authoring/lightmap metadata without treating unsupported layered or procedural shaders as faithful reconstructions. Their original properties and auxiliary textures are supplied in `source_materials/`.
- Materials with `vertexBlendBake` already contain composited terrain albedo, normals and glTF roughness/metallic. Use their baked UV0 and white vertex colour; do not apply the original blend weights a second time. `vertexBlend` retains the source recipe and `source_layers/*.npz` retains original UV0, RGBA and faces for an optional future editable shader. The supported Crash shader needs no new layering shader to display the baked result.

Existing entry points to inspect:

- `src/scene/C2MMap.cpp`: header parsing, material classification, `emitGeometry`, post-load collision/spawn setup.
- `src/scene/GlbMap.h` and `GlbMap.cpp`: `CollisionTriangle`, collision acceleration, movement/ground queries.
- `src/scene/CastScene.h`: mesh alpha/decal/PBR fields.
- `src/app/main.cpp`: map loading, navigation authoring, decal pass settings and status reporting.

## Acceptance tests for the Cadence change

1. An invisible authored box blocks movement even with no corresponding render triangle.
2. A visible decal, glass card and foliage card without authored colliders do not block movement.
3. A trigger is queryable as a trigger but neither blocks nor supports a walking player.
4. The same rotated/scaled prop has aligned visual geometry and collision. Include a mirrored transform and a nonuniformly scaled box.
5. A mesh collider receives no double transformation or double inches-to-centimetres scaling.
6. A C2MX file with empty `COLL` produces no solid collision; ordinary C2M fixtures retain the old behavior.
7. Truncated/overlapping chunks, invalid indices, non-finite coordinates and unknown required schema versions fail cleanly.
8. A settings-only NAVM chunk never reports a native navmesh loaded.
9. The King fixture's extension has **118 authored collider records** (81 boxes and 37 triangle meshes), independently of the legacy loader's render-derived collision triangle count.

Run the affected map/movement tests and the repository-required checks on the new version. The supplied Python tests and old Cadence loader checks do not replace these integration tests.
