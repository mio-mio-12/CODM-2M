# Scanning in v010

Fresh discovery uses os.scandir metadata and indexes bundle directory tables with four workers, bounded to batches of 128. It does not load map geometry. Patch selection and result ordering remain deterministic. Directory links/junctions are not followed during discovery, preventing accidental traversal outside the chosen tree. Discovery errors are included in the catalog error list.

The UI scan worker writes catalog.json before returning. A separate disposable worker builds previews; maps can be selected and exported while it runs. Closing the application or changing the directory stops that worker. Missing previews are regenerated at the next startup. Progress distinguishes discovery from indexing; preview loading is shown separately.

No cache migration or shared cache between releases is introduced. Existing same-folder catalog reuse remains unchanged. Fresh benchmark runs used absent destination catalogs; OS disk caches were not flushed.
