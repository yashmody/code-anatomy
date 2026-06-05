"""Application cache seam.

Empty in Phase 1. Phase 3b fills this with an in-process LRU (and, where
needed, a Redis adapter) so route handlers can decorate hot reads
without each module re-inventing caching.

Filled in by Phase 3b per v2/06.
"""
