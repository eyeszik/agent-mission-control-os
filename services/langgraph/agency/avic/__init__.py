"""ACE x AVIC: governed visual compilation into native SVG.

A brief (PromptIR ``AssetRequirement``), optional raster references and a selected
style profile compile to a typed ``SceneIR``, then to native SVG through an
allowlist emitter, then to a PNG preview through the repository's existing local
Chromium rasterizer. Artifacts are Project OS artifacts stored through the Foundry
store under their N3 roles; approval is the shared artifact approval and
``/approvals/{id}/decide``. Nothing here publishes, deploys or calls a hosted model.
See ``docs/avic.md``.
"""
