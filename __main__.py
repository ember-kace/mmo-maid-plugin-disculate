"""Entry point for the YourBot runner.

The platform validator requires a top-level ``__main__.py`` in the artifact
(yourbot_sdk._validation.validate_artifact, code ``missing_entry_point``).
All handlers live in plugin.py, whose bottom line ``plugin.run()`` performs
the SDK handshake and blocks until shutdown — importing it is the whole job.

Keep this file to the single import. Tests import ``plugin`` directly, so
handler code stays in plugin.py where the existing audit gates scan it.
"""

import plugin  # noqa: F401  — registers handlers and runs the SDK loop
