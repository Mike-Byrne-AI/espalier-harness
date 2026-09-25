# Worked example — adopter contract consumer

This directory shows how an adopter would author a `StringContract`
consumer using the shared infrastructure in `tests/_contracts.py`.

An adopter writes their own consumer when they have a fact (a
canonical event name, a single magic string, a vocabulary set) that
appears in multiple sources and must stay in sync. They register the
rule_id + ceiling in `tests/_surface_expected.py::CONTRACT_CEILINGS`,
write a small parametrized test against `extract_matches`, and use
`# contract: ok <rule-id> <reason>` to opt a single site out when
deliberately diverging (rare; the chip-down keeps opt-outs honest).

`test_example_contract.py` in this directory is the smallest viable
shape: dataclass row + parametrized test + assertion. Real consumers
follow the same pattern at greater scale.
