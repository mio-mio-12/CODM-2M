# CODM-2M-v007 renderer visibility

The visible C2M/GLB geometry excludes source renderers whose m_CastShadows is 3 (Unity ShadowsOnly). Their simplified shadow meshes can overlap real textured surfaces and must not be drawn as ordinary material geometry. No importer texture substitution is required for these omitted helpers.

C2MX META and report.json contain an optional omittedRenderers array. Each record has sourceRenderer, name, reason: "shadows_only", and shadowCastingMode: 3. These are source references, not extra meshes. Dedicated invisible shadow casting is not reconstructed in the exported visual mesh.

Authored COLL records are independent of render visibility and remain intact. Do not derive collision removal from omittedRenderers. Shadow modes 0 (Off), 1 (On) and 2 (TwoSided) remain visually exportable.

A visible material marked unresolvedPlaceholder has no resolved texture in its source assignment. Keep the supplied geometry and material; display the report warning if needed. Do not interpret its name alone as permission to delete geometry or borrow a nearby texture. Highrise has one such room mesh in the tested scene. Runtime weapon finish recovery from the CAST exporter is a separate mechanism.
