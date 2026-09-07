---
name: ck-help
description: Use when the user asks what this kit can do, which capability fits their
  task, or how to get started. Shows the available skills and commands.
platforms:
- linux
- macos
- windows
---

Think harder.
All-in-one ClaudeKit guide. Run the script and enhance output for user.

## Pre-Processing

**IMPORTANT: Always translate `$ARGUMENTS` to English before passing to script.**

The Python script only understands English keywords. If `$ARGUMENTS` is in another language:
1. Translate `$ARGUMENTS` to English
2. Pass the translated English string to the script

## Execution

```bash
consult the embedded help catalog below
```

## Presentation Guidelines

After running the script, present the output with these enhancements:

**1. Add Context When Helpful**
- If user seems new, add a brief welcome
- If user searched for something not found, suggest alternatives
- If showing a category, mention how to dive deeper

**2. Make It Conversational**
- Don't just dump output - introduce it naturally
- Example: "Here are the fix commands:" then show the list
- End with actionable next step: "Try `/fix your-issue` to get started"

**3. Offer Follow-Up**
After showing results, offer relevant next actions:
- Overview → "Want to explore a category? Just say which one"
- Category → "Need details on a specific command?"
- Command → "Ready to use it? Just type the command"
- Search → "Want me to explain any of these?"

**4. Adapt to User Intent**
- Quick lookup → Be brief, just the essentials
- Learning/exploring → Add context and examples
- Problem-solving → Focus on workflow, skip the overview

**5. Handle Edge Cases Gracefully**
- No results? Suggest similar commands or categories
- Typo detected? Ask "Did you mean X?"
- Empty input? Show overview with friendly intro

## Example Interactions

**User:** `/ck-help`
**You:** Here's an overview of ClaudeKit commands:
[script output]
What would you like to explore?

**User:** `/ck-help fix`
**You:** Here's the fixing workflow:
[script output]
Which issue are you dealing with?

**User:** `/ck-help add login page`
**You:** For building a login page, I'd recommend:
[script output]
Try `/cook add login page` to implement directly, or produce an implementation plan then implement the plan for explicit planning first.

## Important: Correct Workflows

- **produce an implementation plan → implement the plan**: Plan first, then execute the plan
- **`/cook`**: Standalone - plans internally, no separate produce an implementation plan needed
- **NEVER** suggest produce an implementation plan → `/cook` (cook has its own planning)

## AgentKit — available capabilities

### Skills
- aesthetic
- ai-multimodal
- backend-development
- better-auth
- chrome-devtools
- claude-code
- code-review
- databases
- debugging
- devops
- docs-seeker
- frontend-design
- frontend-design-pro
- frontend-development
- google-adk-python
- mcp-builder
- mcp-management
- media-processing
- mobile-development
- payment-integration
- planning
- problem-solving
- repomix
- research
- sequential-thinking
- shopify
- skill-creator
- template-skill
- threejs
- ui-styling
- ui-ux-pro-max
- web-frameworks

### Commands
- /ck-help
- /cook
