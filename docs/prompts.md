# Prompt engineering log

This file tracks prompt versions and the eval delta each iteration produced.
Prompts themselves live in `src/prompts/*.md` and are loaded by name with a
version pin.

Format per entry:

```
## YYYY-MM-DD — <prompt_name> vN
- Change: <what>
- Why: <which failure mode>
- Eval before: <metric>
- Eval after: <metric>
- Verdict: keep / rollback
```

Empty until the first iteration lands.

## 2026-05-12 — classify_layout v1
- Change: initial prompt for Haiku 4.5 layout classifier; decision rubric + 2 few-shot exemplars (ixonia_business_basic, generic_us_bank).
- Why: M1 classifier node needs a versioned prompt; cache-friendly layout (stable instructions first, dynamic {chunk_text} placeholder last).
- Eval before: n/a
- Eval after: n/a (evals land in M2+ once extractors are wired)
- Verdict: keep
