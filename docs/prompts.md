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
