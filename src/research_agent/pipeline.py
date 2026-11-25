class Pipeline:
    """A plain state machine for ordered steps, saved state, and retries.

    The pipeline coordinates agents rather than acting as an LLM.
    """
