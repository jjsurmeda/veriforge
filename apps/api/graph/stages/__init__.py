"""The Auto pipeline, one module per stage (TRD §7).

`state.py` holds the typed state every stage takes and returns, plus the
`StageEnv` naming the session, engine and step timers a stage runs inside. A
stage never reads a local from another stage: what it needs is a field on the
state or an attribute of the environment.
"""
