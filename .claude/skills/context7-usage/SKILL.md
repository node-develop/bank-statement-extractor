---
name: context7-usage
description: How and when to use mcp-context7 to pull current docs for LangGraph, LangChain, LangSmith, FastAPI, pdfplumber, Pydantic v2. Use BEFORE writing code that touches a new API surface. Do NOT use for general web search.
---

# Using mcp-context7

## When to use

Before writing or editing code that touches an API surface you haven't
verified in this session:

- `langgraph.StateGraph`, `MessagesState`, checkpointers
- `langchain_anthropic.ChatAnthropic`, structured output
- `langsmith.traceable`, eval CLI
- `fastapi.UploadFile`, `BackgroundTasks`, dependencies
- `pdfplumber.Page.extract_tables`, table settings
- `pydantic.v2` validators, model_config

## How

```
1. mcp__context7__resolve-library-id  query="langgraph"
   → returns library_id "langgraph-ai/langgraph"
2. mcp__context7__query-docs library_id="langgraph-ai/langgraph"
                              query="StateGraph parallel branches join reducer"
   → returns 1-2 doc snippets to ground your edit
```

## Rules

1. **Resolve once per session, then reuse the library_id.** Re-resolving
   on every call burns tokens.
2. **Specific queries.** "How do I X" wastes the budget. Ask
   "StateGraph parallel branches join reducer" not "how does langgraph work".
3. **Cite the snippet in your code comment** when the API is non-obvious:
   `# context7: langgraph parallel branches require Annotated[..., reducer]`.
4. **Don't substitute for testing.** Docs say "this works"; tests prove it.
