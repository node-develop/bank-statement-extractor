---
name: anthropic-models-routing
description: Which Anthropic model to use for each LangGraph node and subagent — Sonnet 4.6 for extraction, Haiku 4.5 for routing/critic. Use whenever instantiating a ChatAnthropic in code or picking a `model:` in an agent frontmatter. Do NOT pick Opus unless explicitly justified — cost outweighs gains here.
---

# Anthropic model routing

## Defaults

| Use case                                | Model              |
|-----------------------------------------|--------------------|
| Layout classification (single label)    | `claude-haiku-4-5` |
| Account / summary extraction            | `claude-sonnet-4-6`|
| Transactions extraction (chunked)       | `claude-sonnet-4-6`|
| Critic loop (decide which to retry)     | `claude-haiku-4-5` |
| Subagents (code-writing)                | `claude-sonnet-4-6`|
| Evaluator (read-only)                   | `claude-haiku-4-5` |

## Why not Opus

For a 99-page redacted statement, Sonnet 4.6 reconciles within budget.
Opus 4.6 doubles cost without a measurable reconciliation gain on this
shape of data. Reserve Opus for cases where Sonnet has demonstrably
failed and you have a LangSmith eval showing the gap.

## ChatAnthropic instantiation

```python
from langchain_anthropic import ChatAnthropic

llm_extract = ChatAnthropic(
    model="claude-sonnet-4-6",
    max_tokens=4096,
    temperature=0,
    timeout=60,
)
llm_route = ChatAnthropic(
    model="claude-haiku-4-5",
    max_tokens=512,
    temperature=0,
    timeout=20,
)
```

## Structured output

For account / summary / transactions, use LangChain structured output:

```python
llm_extract.with_structured_output(Summary).invoke([...])
```

This binds a pydantic model and uses Anthropic's tool-call mode for
strict schema. Do not parse JSON from free-form text — that is a
hallucination vector (rule 12).

## Cache discipline

Put the prompt template *first*, the statement page *last*. Anthropic's
prompt cache is prefix-based — moving the stable instructions to the
front gives ~10× discount on repeated calls.
