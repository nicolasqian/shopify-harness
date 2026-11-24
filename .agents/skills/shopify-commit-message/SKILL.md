---
name: shopify-commit-message
description: Write a short English Conventional Commit message from the current repository changes. Use when the user asks for a Git commit message, commit title, or concise summary suitable for committing this Shopify theme's staged or unstaged changes.
---

# Conventional Commit Message

Inspect the current Git changes and return a concise English commit message that follows the Conventional Commits format.

## Workflow

1. Inspect `git status --short`.
2. If staged changes exist, analyze only the staged diff; otherwise analyze the unstaged diff and relevant untracked files.
3. Read recent commit subjects when useful, but use the Conventional Commits format as the governing standard.
4. Identify the primary intent of the change and choose the most specific valid type.
5. Group the changed behavior by intent. Keep closely related changes in the subject; use body lines only when the commit contains materially different changes that would be unclear in one line.
6. Start with a commit subject in this form:

   ```text
   <type>[optional scope][!]: <imperative description>
   ```

## Commit Rules

- Use lowercase types: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`, or `revert`.
- Use a short lowercase scope when it clarifies the affected area, such as `header`, `product`, `locales`, or `theme`.
- Use `feat` for a user-visible capability, `fix` for a bug correction, `docs` for documentation-only changes, and `chore` for maintenance or configuration changes.
- Use `!` after the type or scope only when the change intentionally breaks an existing contract, such as a public interface or Shopify setting/schema compatibility.
- Write an imperative, specific, grammatically complete description; omit a trailing period and avoid vague text such as `update files`.
- Keep the complete subject to 72 characters or fewer where possible.
- Prefer a single subject line when all changes serve one coherent intent.
- For materially different changes in the same commit, write one subject for the overall intent, then add a blank line and concise `- ` body lines describing each distinct change. Do not create multiple Conventional Commit subjects.
- Keep every subject and body line on one physical line. Never insert a backslash to represent a line break or wrap in the middle of a phrase or word.
- Before returning the message, check spelling and grammar. Make sure every word is complete and every line reads naturally in English.

## Output and Safety

- Return only the plain-text commit message, with no Markdown fences, quotation marks, or explanation.
- Normally return exactly one subject line. Add a body only when there are materially different changes worth calling out.
- Do not stage files, create a commit, or modify the working tree.
- If there are no changes, return `No changes to commit.`

## Examples

```text
feat(cart): add quantity selector
fix(product): preserve selected variant on refresh
docs: clarify theme validation rules
chore: ignore local Codex files
```

For a commit with distinct changes:

```text
fix(nav): correct navigation destinations

- route the service and contact links to the contact page
- preserve external link behavior in the mobile menu
```
