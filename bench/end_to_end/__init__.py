"""End-to-end bench.

Receiver-side verification: does Claude actually act on hook output?
The corpus runs real Claude Code as a subprocess against scenario
fixtures and asserts on agent behavior. See bench/end_to_end/README.md
for cost discipline and how to add a scenario.
"""
