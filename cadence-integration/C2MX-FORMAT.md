# C2MX 1: C2M with separate authored collision

The file extension stays `.c2m`. The beginning is a normal C2M v3 map. A chunk directory and a fixed footer are appended after the ordinary C2M data. This was designed against the installed Cadence `src/scene/C2MMap.cpp`; its existing loader ignores trailing bytes and can load the visual map. This is a local extension, not an official C2M revision.

**Existing Cadence does not consume the new collision chunk yet.** Until the integration below is implemented it continues generating approximate collision from render triangles.

## Base C2M

- Magic `C2M`, file version 3, game ID 255 (unassigned/custom; do not mislabel CODM as an existing CoD version).
- World object 0 contains transformed world geometry and prop surfaces. Each surface keeps its source object name, material index and triangle range. This first implementation flattens static instances, while source renderer/mesh IDs, transforms, batch ranges and atlas IDs are retained in the GLB node extras.
- Textures are ordinary PNG files in `images/`, next to the map. Keep this folder with the C2M.
- Visual coordinates are right-handed, Z-up, inches. Unity point `(x,y,z)` in metres becomes `(-x,-z,y)/0.0254`. Cadence multiplies C2M coordinates by 2.54 to obtain centimetres. Existing user map scale applies afterward.
- Base C2M materials are compatibility approximations. C2MX material records retain the explicit blend, alpha, PBR and decal settings that the old loader otherwise infers from names.

## Binary envelope

All envelope integers are **unsigned little endian**. The footer is exactly the final 32 bytes of the file:

| Offset | Type | Meaning |
|---:|---|---|
| 0 | char[4] | `C2MX` |
| 4 | uint32 | Envelope version, 1 |
| 8 | uint64 | Absolute file offset of chunk directory |
| 16 | uint64 | Directory byte length |
| 24 | uint32 | Directory entry count |
| 28 | uint32 | Reserved flags, zero |

Directory entries are 24 bytes each:

| Offset | Type | Meaning |
|---:|---|---|
| 0 | char[4] | Tag, e.g. `COLL` |
| 4 | uint32 | Chunk version, 1 |
| 8 | uint64 | Absolute payload offset |
| 16 | uint64 | Payload byte length |

Payloads are UTF-8 JSON without a terminator. Payload starts and the directory are aligned to 8 bytes; their lengths exclude alignment padding. The directory ends immediately before the footer. Validate using subtraction to avoid integer overflow; reject truncated, overlapping or duplicate chunks, unsupported known-chunk versions and offsets outside the file. Missing footer means an ordinary C2M. A present but corrupt footer is an error, never a reason to silently use fallback collision.

The supplied `C2mxReader.h` is a standalone C++17 envelope reader. `codm_compiler.formats.read_extension` is the Python reference reader. JSON parsing is deliberately separate from the C++ envelope reader so Cadence can choose its JSON dependency.

## META: provenance, completeness, materials and lighting

`schema` is `codm.c2mx/1`. Important fields:

- `collisionPolicy`: `authored_only`.
- `collisionComplete`: whether all encountered colliders in the **selected scenes** decoded. This does not assert that the user selected every scene or streamed tile belonging to the level.
- `collisionErrors`, `errors`, `warnings`: inspect before activating gameplay. A convex MeshCollider whose cooked hull has not been decoded is explicitly incomplete.
- `collisionScope`, `scenes`, `sourceRoot`, `loadedBundles`: extraction provenance.
- `renderFidelity`: currently `approximate_custom_shaders`. Layered terrain, procedural shader effects, some cubemaps and baked-lightmap application are not reproduced exactly. Additional textures and original material properties remain in the package.
- `visualMaterials`: indexed as the base C2M material table. `c2mMaterialName` is the exact name written there; `name` is the source/atlas-variant name. Use the integer material index during loading, rather than matching ambiguous display names.
- Material fields: `decal`, `blend` (`alpha`, `multiply`, `additive`), `alpha` (`OPAQUE`, `MASK`, `BLEND`), `cutoff`, `doubleSided`, `color`, `metallic`, `roughness`, `emissive`, `textures`, `shader`, source blending factors and render queue. Texture paths are relative to the map folder. Reject absolute paths or traversal outside the package.
- `lighting`: original RenderSettings, Light components and LightmapSettings. Light transforms are explicitly named `unityWorldMatrix` and remain Unity column-major metres. Lightmap image references are exported separately. They are not silently substituted for a usable renderer lighting implementation.

## COLL: physics independent of visible surfaces

```json
{
  "schema": "codm.collision/1",
  "coordinateSystem": "RH_Z_UP",
  "units": "inches",
  "colliders": [
    {
      "id": "BuildPlayer-Example:101",
      "name": "InvisibleBarrier",
      "kind": "BoxCollider",
      "trigger": false,
      "enabled": true,
      "layer": 0,
      "center": [0, 0, 0],
      "size": [40, 20, 80],
      "matrix": [1,0,0,0, 0,1,0,0, 0,0,1,0, 10,20,30,1]
    }
  ]
}
```

Common fields:

- `id` is the serialized file name plus path ID, not just a GameObject name. Several colliders may belong to one object.
- `matrix` is a 4x4 **column-major** local-to-world affine matrix. Translation, `center`, `size`, `radius` and `height` are in C2M inches; matrix basis vectors retain scale. To convert a resulting world point to Cadence centimetres multiply by `2.54 * scaleMultiplier` exactly once.
- `layer`, `trigger`, `enabled`, original `source` properties and optional `physicsMaterial` are retained. Unity layer numbers alone do not establish the full project collision matrix. Apply an explicit layer policy; keep triggers out of blocking/walkable triangle lists.
- Box: `size` is the full local extent. Transform the eight `center ± size/2` corners with `matrix`. Include only enabled non-trigger boxes in solid collision. Preserve triangles even when no visual surface exists.
- Sphere: `radius` and `center` are local. `scalePolicy=unity_max_axis` means use the largest absolute basis scale for radius, not an ellipsoid from naïvely applying the whole matrix to a sphere.
- Capsule: `axis` is 0=X, 1=Y, 2=Z; `height` includes both caps. `scalePolicy=unity_axis_height_max_perpendicular_radius` preserves Unity's axis/scale intent. Height scales along the capsule axis; radius uses the larger perpendicular scale. Clamp total height to at least twice the resulting radius. Keep analytic capsule data; any tessellation is an explicitly approximate query/debug representation.
- Mesh: `vertices` and `triangles` are already in **world** C2M inches. `matrix` is identity and `center` zero. Do not reapply the source transform. Triangles have corrected winding. `convex=false` is the source triangle-mesh collider. `convex=true` retains the source mesh but currently sets `collisionComplete=false`; Cadence must cook a convex hull or decode the original cooked data before calling it exact.
- Physics shape transforms with shear need an explicit engine policy; preserve the matrix and flag unsupported cases rather than silently orthogonalizing it.

`COLL` is authoritative even when it contains zero colliders. Never augment it with visual triangles, decals, glass or foliage merely to make collision “look complete.” Decals cannot create collision unless a distinct authored collider explicitly does so.

## NAVM: navigation preservation

`schema` is `codm.navigation/1`.

- `status=not_found_in_selected_scenes`: no recognized navigation component/payload found.
- `status=settings_only`: navigation build settings were found, but no native baked payload was decoded. This is the tested King result.
- `status=native_payload_preserved`: one or more native NavMeshData serialized objects were preserved.
- `runtimeReady=false`: none of these statuses claims to be a Cadence navigation graph.
- `assets[]` identifies each payload/component, its source type, decoded settings where available and the original `dataBase64` bytes. `kind` distinguishes `native_payload` from `component_settings`. Loose `.bin` and `.json` copies live in `navigation/` for inspection.

For settings-only maps, Cadence may build a **new** navigation mesh from authored `COLL`, using the retained agent radius/height/climb/slope when applicable. Label that as generated navigation. Do not report it as the game's original navmesh. A future decoded polygon/adjacency chunk should use its own tag/version and carry links, areas, agent settings and coordinate conventions explicitly.

## Compatibility tests

Preserved source metadata may contain `{"nonFiniteFloat":"NaN"}`, `"+Infinity"` or `"-Infinity"` markers for non-finite source scalars. These markers retain the original meaning without invalid JSON. Do not use them as numeric lighting/physics inputs. `nonFiniteSourceFields` on a lighting record identifies affected paths. SBNC has two such ambient-probe coefficients. Exported geometry and runtime collision numbers remain strictly numeric and finite.

The Python tests cover coordinate handedness, nonuniform scale normals, projector clipping, old/new atlas bitfields, GLB alignment, collision independence and corrupt C2MX directories. The generated King map was also loaded through the installed Cadence C2M and GLB test executables. Those existing executables validate **legacy visual loading**, not consumption of the new collision chunk.
