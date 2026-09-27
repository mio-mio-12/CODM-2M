# CODM-2M-v010

- Faster fresh scans using directory-entry metadata and four bounded indexing workers.
- Maps become usable when indexing completes; preview generation runs separately.
- Scan status shows discovery and bundle-indexing progress.
- Fixes patch selection for paths where Extract occurs before PersistentData.
- No cross-version cache sharing or migration.

Fresh-catalog benchmark on the local installation: v009 4.735 seconds, v010 3.218 and 3.265 seconds, approximately 32% less time. All runs began without a destination catalog, but Windows disk caches were warm. This is not a cold-disk comparison against the earlier three-minute scan. The v009 comparison includes the folder-ordering fix so it can run on the current directory layout. Catalog contents matched exactly: 14,834 readable bundles, 8,979 scenes, 31 unreadable bundles.

Validation: 68 automated tests passed. The packaged scan completed in 6.56 seconds including worker startup, with exact catalog parity. Its separate preview worker generated 87 images in 13.25 seconds with zero errors. These measurements used warm OS disk caches.
