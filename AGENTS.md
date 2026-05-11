# AGENTS.md

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:

- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:

- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:

- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:

- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:

```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.

## Project-Specific Guidelines

### 0. Working Principles

- Before implementing or modifying code, first inspect the current structure of the relevant service.
- Uncommitted changes in the local working tree may belong to the user. Do not revert or overwrite them.
- New services must follow the structure and patterns of existing services: `user-service`, `product-service`, `payment-service`, `order-service`, and `api-gateway`.
- Routers should keep the HTTP boundary thin, and business logic should live in the `services/` layer whenever possible.
- If deviating from the project conventions is necessary, announce it before writing code using the format: `⚠️ Convention deviation: [reason]`.

### 1. Required Reference Documents

Before starting work, read the following documents in order. If documents conflict, domain rules in documents 1 and 2 take precedence.

1. `docs/ERD_structure.md` — models, constraints, and status values
2. `docs/service_function_definition.md` — endpoint contracts and inter-service call flows
3. `docs/micromart_design.md` — overall architecture and design intent
4. `docs/dev_convention.md` — coding conventions, file structure, and security rules

Follow the latest rules in `docs/dev_convention.md` for dependencies, test directories, Dockerfiles, and local Compose configuration.

### 2. Phase-Based Workflow

- Implement work by Phase.
- Before starting each Phase, briefly explain the core concepts and major tradeoffs.
- After completing each Phase, write a References document.
- If a commit is created, write the References document immediately after the code commit.
- If a decision in Phase N affects Phase N+1, explicitly document it in References.

Each References document must include the following sections:

- Role description
- File structure
- Key design decisions
- Common errors and troubleshooting
- Why this design was chosen

### 3. Coding Standards

- Functions and classes must include docstrings explaining their role and key decision criteria.
- Non-obvious logic must include inline comments explaining the reason behind it.
- Do not add comments for obvious logic.
- Do not add unnecessary features, abstractions, or configurability.
- Limit changes to files directly related to the request.

### 4. Security and Consistency Checklist

After implementation, verify the following:

- Authentication/authorization: Do not trust external input such as `user_id` or `role`.
- Internal APIs: No internal route should be accessible without `X-Internal-Token`.
- Sensitive data: Do not log raw passwords, tokens, or secrets.
- State consistency: Failed paths must not leave partial or intermediate state in the database.
- Idempotency: Duplicate requests must not cause double processing.

### 5. Observability Standards

Each service implementation must include the following:

- Counter/Histogram metrics for key business events
- Structured log fields: `service`, `trace_id`, `span_id`, `event`
- Span creation and TraceContext propagation for inter-service calls

### 6. Code Review Handling

- Before accepting review feedback, check whether the reasoning is valid and whether it conflicts with the project design.
- When applying review feedback, state the reason for accepting or rejecting it in one line.
- If industry practice and project rules differ, explain the tradeoff and let the user decide.

### 7. Documentation Work

- Before updating documentation, inspect the actual code, configuration, requirements, Docker/Compose setup, and test directory structure.
- If the request is documentation-only, do not change code.
- Model changes must be reflected in `docs/ERD_structure.md`.
- Endpoint and call-flow changes must be reflected in `docs/service_function_definition.md`.
- Architecture and implementation-status changes must be reflected in `docs/micromart_design.md`.
- Shared development convention changes must be reflected in `docs/dev_convention.md`.

### 8. Concept Explanations

For conceptual questions, compare with industry practice and clearly explain the major tradeoffs.
