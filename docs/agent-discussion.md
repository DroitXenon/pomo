# Agent Discussion

Shared discussion space for Pomo teammates and their coding agents. Use it to exchange proposals, questions, replies, decisions and handoffs across separate chats and branches.

Project instructions live in [AGENTS.md](../AGENTS.md), implementation progress in [README.md](../README.md), and the current transport contract in [protocol.md](protocol.md). This discussion log complements those documents; proposals here do not automatically change the project contract or task scope.

## How to Participate

1. Read the relevant existing entries before starting a task or proposing a shared change. Check the branch and commits you are working from so you know which version of the discussion you have.
2. Append an entry using the template below. Identify the teammate you are working with and the agent/tool writing the entry. Use a descriptive ID such as `2026-10-31-alex-camera-observations`; author/topic-based IDs reduce collisions across branches.
3. Explain the idea or question, its reasoning and the affected files or interfaces. Separate observed behaviour from assumptions and proposed changes.
4. Reply by appending another entry and referencing the original ID. Preserve other contributors' words and the discussion history. Correct an earlier claim with a follow-up entry.
5. Record decisions with the actual decision maker or merged pull request as evidence. An agent proposal is not a team decision. Continue implementation within the task owner's requested scope.
6. When an agreed change is implemented, update the relevant code, tests and canonical documentation through the normal task workflow. Add a short follow-up linking the result and any remaining work.

Keep entries concise and relevant to Pomo. Include repository paths, commit IDs, test results or pull-request links when they support the discussion. Keep credentials, private `.env` values and camera images/video out of this file.

## Sharing Through Git

This is an asynchronous Git discussion log. A local edit becomes available to teammates after it is committed, pushed and brought into their checkout. It does not send notifications or messages to another agent automatically.

- Add discussion entries on the branch used for the task and share them through the team's normal commit/pull-request workflow.
- Merge discussion updates into the shared branch promptly when they affect other work. Teammates then update their checkout before relying on those entries.
- Respect existing local changes when updating a branch. Do not discard work or rewrite shared history to synchronise this file.
- When branches add entries concurrently, keep both entries during conflict resolution. Avoid editing the same existing entry from multiple branches.
- Follow the task owner's authorised scope for committing, pushing or merging. Writing an entry does not itself authorise publishing changes.

## Entry Template

Copy this template to the end of the discussion log and replace the placeholders. Leave the template itself available for the next contributor.

```markdown
### YYYY-MM-DD-author-short-topic

- Date: YYYY-MM-DD HH:MM UTC-offset
- Author: <teammate name> / <agent or tool>
- Type: Proposal | Question | Reply | Decision | Handoff
- Related entries: <entry IDs, or none>
- Context: <task, branch/commit and relevant repository files>

**Idea or response:**
<What you propose, need to know, or want to tell another contributor.>

**Reasoning and evidence:**
<Observed behaviour, alternatives, tradeoffs and any checks performed.>

**Next step:**
<A concrete action or question; identify an agreed owner or leave it unassigned.>

**Decision evidence, if applicable:**
<Who made the decision or which merged PR records it; omit for open proposals.>
```

## Starting Topics

These are open questions from the current Phase 2 roadmap, not agreed implementation decisions:

- What camera-to-backend observation format should carry presence, timestamp and camera availability?
- Which configurable absence durations and reminder cooldowns should be evaluated, and how will simulated observations test them?
- How should camera, backend behaviour and simulator work be divided while keeping state transitions in the backend?

## Discussion Log

Append new entries below this line; replies should reference the entry they address.
