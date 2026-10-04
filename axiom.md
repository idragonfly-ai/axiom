Polymorphic Source Mapping: axiom_sources handles paper, wiki, local_note, and technical_doc via source_type.
axiom_chunks links to source_id foreign key.

Dual Ingestion Compatibility: Wiki metadata (categories, revision tags, url slugs) lives in axiom_sources.metadata_json, while text chunks feed standard token slicing.

Bi-Directional Graph Readiness: axiom_edges indexes both source_concept_id and target_concept_id separately, letting queries traverse incoming or outgoing edges cleanly.
Alias Normalization: axiom_aliases prevents fragmenting identical concepts across text variants.

Deployment Sequence
1.
Run schema.sql in MariaDB.
2.
Ingest initial docs/notes/reference texts via chunker.py.
3.
Hit api.php?q=VFIO+IOMMU+Group+Isolation (returns status: miss, logs job to axiom_queue).
4.
Run python3 worker.py via cron/daemon loop to consume queue, hit local llama-server, and materialize nodes/edges.
5.
Hit api.php again to confirm instant JSON hit.
