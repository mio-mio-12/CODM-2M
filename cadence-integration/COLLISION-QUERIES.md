# Collision query audit — CODM-2M-v008

The collision.json and C2MX COLL records already preserve layer, trigger and physicsMaterial (including m_Name). A collider is not proof that it should block every query. Cadence should keep player movement, bullet traces and grenade queries separate. Gameplay and tactical sidecars must never become solid collision automatically. Respect disabled/trigger records and avoid adding a second set of visual-mesh collision over authored collision.

Observed in Highrise and Shipment CN visual scenes:

- Layer 12: 549 colliders, all PhysicalPenetrateStone, including wall helper objects.
- Layer 14: 205 colliders with metal, wood, glass, cloth and other materials, including PhysicalGrenadeForbid and PhysicalGrenadeBounce.
- Layer 37: two Shipment colliders, one PhysicalMetal_AbleToPass and one PhysicalRubber.
- Layer 47: 33 colliders with reflection-probe object names, PhysicalDefault.

These counts include inspected source collider records, not necessarily enabled export records. This audit does not establish layer names or the game's weapon query masks. Material names indicate distinct surface/query treatment, but are not verified penetration damage/thickness coefficients. PhysicalPenetrateStone must not be silently interpreted as either completely bulletproof or zero-resistance without testing. Reflection-probe helper colliders are another likely source of unintended gameplay blockage if all layers are treated as solid.

For diagnosis, show hit collider ID/name, layer, trigger and physicsMaterial.m_Name in Cadence's shot trace overlay. Compare blocked locations against these classes. Keep configurable per-query layer/material policies; do not globally remove collision or infer bullet pass-through solely from invisibility. Authentic penetration needs the game's query masks and material/weapon rules, which have not been recovered in this release. No collision filtering is changed in v008.
