# Tool Registry

This directory is the Layer 1 source of truth for public tool capability contracts.

Each `tools/*.yml` file owns:

- capability boundary;
- public parameters;
- default routing/fallback policy;
- implementation and handler owner paths;
- downstream schema/SOP/prompt references.

Downstream artifacts may summarize these contracts, but should not invent separate
tool behavior.
