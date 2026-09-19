# Crash terrain blending

Supported shader: `CODM/Terrain/3Tex_VertexBlend_NormSpecRealtime`.

The compiler bakes this shader into ordinary albedo, normal and roughness/metallic textures. Cadence does not need a new terrain shader to show its texture transitions. Apply the C2MX PBR material overrides and use the exported UV0. Baked vertices are white; source vertex colours are weights, not a tint.

The material recipe is retained in `META.visualMaterials[].vertexBlend`. Original UV0, vertex RGBA and source triangle indices are retained in the referenced `source_layers/*.npz`. Those indices describe the original compact source surface, not the duplicated/reordered baked charts; source mesh/renderer IDs identify the game geometry. This preservation is for future authoring support, not an implemented native editable-layer importer.

## Verified blend rules

These rules were recovered from the installed Crash material properties and D3D11 pixel program, including its resource and constant bindings. They describe the full normal-map branch, not its reduced-detail one-pass branch.

1. Sample `_BaseTexture` and `_BaseNormal` with `_BaseTexture` scale/offset. Sample `_Albedo1` and `_Normal1` with `_Albedo1` scale/offset. Sample `_Albedo2` with its own scale/offset. Normal textures do not use their independent saved transforms in this shader.
2. Let `r` be interpolated vertex red when `_ALBEDO_VERTEX_R` is enabled, otherwise zero. Let `g` be interpolated green when `_ALBEDO_VERTEX_G` is enabled, otherwise zero. Limit green to `min(g, 1-r*(1-_MaskLayer2))`.
3. Albedo is `lerp(lerp(base, albedo1, r), albedo2, g)`. Albedo texture samples are blended in linear colour space, then encoded into the output PNG's sRGB channels.
4. Blend base/first packed normal RGB by red. RG holds normal XY and B holds smoothness. Green moves XY toward 0.5 by `saturate(g * _waterSmoothMult)`. Unpack XY, apply `_BumpScale`, reconstruct Z, and normalize. Smoothness moves toward `_Smoothness2` by `g * _SmoothnessScale2`.
5. Metallic follows the same red-then-green interpolation using `_BaseMetallic`, `_Metallic1`, and `_Metallic2`.
6. Blue controls height-dependent wetness: `b * (1-smoothstep(0, max(_waterTrans, 0.01), worldY-_waterHeight))`. This scales albedo, smoothness and metallic using the corresponding material multipliers. Crash's tested materials put the water height at -100 metres, so this is normally inactive there.

7. With `_use_g_control_wet_ON`, combine wetness with raw interpolated green: `wet = wet + green * (1-wet)`. This uses green independently of `_ALBEDO_VERTEX_G` and its masked albedo weight. Verified against the installed D3D11 variant and SBNC's six affected ground materials. The baked output retains all their triangles.

The bake excludes game lighting, fog, reflection probes and exposure. It is a portable material approximation, not an identical rendering of the game. Height-blend variants remain explicitly unsupported. Other shader names are not assumed to follow these rules.

## Bake tradeoffs

Triangle charts preserve the source UV directions and interpolate weights across each triangle. Independent charts handle overlapping/repeated source UVs without overwriting another surface's painted weights. Eight-pixel gutters reduce filtering bleed. Large/distant meshes have a bounded pixel budget; inspect `limitedCharts` for resolution reduction. `flatNormalCharts` reports collapsed source UVs whose tangent direction is undefined. Strong minification can reveal chart seams.

For a future native layer renderer, keep source UVs and weights as dedicated attributes, bind all layers with their individual tiling, and reproduce the rules above. Do not multiply vertex RGB into the final albedo or use its alpha as surface opacity. That future route could preserve unlimited texture tiling without the bake's resolution tradeoff.
