# Additive effects in CODM-2M-v007

Apply material behavior from META.visualMaterials, not asset-name guesses. A material with blend="additive", srcBlend=5 and dstBlend=1 uses source-alpha/one RGB blending; srcBlend=1,dstBlend=1 uses one/one. These Unity factor values and resolvedRenderState identify the primary visible source pass. Preserve tint/color and unlit appearance; disable depth writes while retaining appropriate depth testing. Do not turn these visual effects into collision.

C2M references the original images and codm_additive techset; C2MX contains the source blend factors, color/tint and original shader properties. Black RGB contributes no emitted light under additive blending even when source alpha is opaque. A consumer that ignores the additive state will still draw black rectangles; implement this material policy in the consumer.

GLB uses glbColorTexture and glbColorFactor internally to produce a standard BLEND + KHR_materials_unlit material. The preview converts emitted linear RGB to straight alpha: alpha=max(emitted RGB), RGB=emitted/alpha, then encodes RGB to sRGB. Source alpha/tint alpha are included for SrcAlpha/One. LDR clipping and 8-bit quantization apply. An alpha blend cannot equal true additive compositing against arbitrary backgrounds.

Use original textures for a native C2M additive pass. Do not apply additive blending or source tint a second time to the GLB alpha preview. Opaque and cutout materials are not subject to black-to-alpha conversion. Static particle masks/animation and other unimplemented source effects remain in the source metadata; this change specifically generalizes blend recognition and emitted-light previews.

No image file-format change is made in v007: textures remain PNG.
