# Code review

Review the **diff**, not the agent's report. The reviewer re-runs the claimed
checks (`agents.md`) and answers these per change:

1. **Outside assumptions.** What does this assume about something we don't
   control: model output shape, provider API fields, OS, CI runner tools,
   lockfile platforms, a default value? Is each assumption tested against a
   real capture (`testing.md`)?
2. **Code vs intent.** Does the code do what its comment, the TRD and the
   relevant ADR say? Name any line where they disagree.
3. **Which eval would catch it?** If this were wrong, which acceptance or
   fast20 item would fail? If none, should one exist?
4. **Product path.** Does a test, script or harness take a path no user
   takes (`source="auto"`, a pinned model, a different corpus, a dev-only
   transport)?
5. **Blast radius.** Callers checked (CodeGraph `explore`)? Defaults flipped?
   Full suite run?

Quality-affecting changes (graph, retrieval, decisions, prompts, model
parameters) also need the eval gate before merge (CLAUDE.md).
