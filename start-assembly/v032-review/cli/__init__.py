"""Command-line interface for START planning (ISSUE-27).

File-in / file-out only: every input is a persistence envelope
(``persistence.load_envelope``), every output is a ``result`` envelope
(``persistence.save_envelope``). No interactive mode, no UI, no
renderer, no network. Run as ``python -m cli`` — there is no
``[project.scripts]`` console-script entry point.
"""
