"""Project export to Google Drive with an optional Notion record.

The runner collects a project's output files, builds a content-addressed
manifest, zips the files that changed since the last export, uploads the zip
to a Google Drive folder through the Drive v3 API with a service account,
verifies the upload by reading its metadata back, and records it in a Notion
database. ``RUNNER_MODE`` defaults to ``dry_run``, which builds the zip locally
and makes no network call. Credentials are read from the environment only.
See ``docs/drive-export.md``.
"""
