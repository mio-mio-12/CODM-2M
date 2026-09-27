# Four-layer terrain materials

`CODM/Terrain/4Tex_Mask_Terrain` surfaces are baked to ordinary color, normal, and metallic/roughness images for GLB and C2M. Cadence should display the baked images and retain the original `terrainMask` material metadata and `terrainMaskBake` mesh metadata for future native shader support. The source mask and four packed splat textures remain in the exported source layers.

The packed colors are reconstructed from each splat's G/B channels and its `BasisX`, `BasisY`, and `Offset` material values. The mask selects the four layers through RGB plus the remaining weight. The mask's world XZ projection scale is inferred for Azur GW; it is recorded in `terrainMask.controlWorldScale` so a native implementation can refine it.
