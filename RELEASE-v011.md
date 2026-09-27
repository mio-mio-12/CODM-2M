# CODM-2M-v011

- Bake Azur GW's four-layer, control-mask terrain materials into textured GLB/C2M surfaces. The bake reconstructs the packed terrain colors using the material's PCA basis and blends the four splats using the control mask.
- Use the authored tint for untextured static-color Unity materials, including Azur GW's sea-bottom surface.
- Preserve the original terrain shader and texture references in export metadata for further Cadence integration.

Validation: 70 automated tests passed. A focused export of Azur GW's two four-layer terrain renderers baked 24,697 triangles without material errors; a rendered GLB check showed textured coastline terrain rather than white ground.

The terrain control map uses an inferred world-space projection scale. Colors and layer placement are reproduced, but exact in-game lighting is outside this bake. These materials currently use the CPU bake path.
