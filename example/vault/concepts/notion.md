---
title: "Notion"
type: concept
kind: tool
aliases: []
mentions: 2
---
A temporary store for user progress in the Beacon prototype.

## Mentions

### [[calls/2024-03-12-018e321a|Beacon onboarding plan: mockup, copy, and prototype storage]] (2024-03-12)
Sam and Lee chose Notion as a temporary prototype store for user progress before migrating later.
> Sam | 01:32
> One more thing - we need to decide where to store user progress. I suggest Notion for now, just for the prototype.
> 
> Lee | 01:55
> Fine, Notion is good enough for the prototype. We'll migrate later.
> 
> Sam | 02:10
> Deal then. I do the mockup, you do the copy, we meet on Friday.
> 
> Lee | 02:22
> Perfect, see you Friday.

### [[calls/2024-03-15-018e41d2|Beacon onboarding implementation, database choice, and analytics]] (2024-03-15)
Notion remained the demo storage for user progress despite rate limits.
> Lee | 01:01
> I can start on Monday. One blocker though - the Notion storage for user progress. The API rate limits are worse than I thought.
>
> Lee | 01:26
> Three requests per second per integration. Fine for the prototype demo, but it will fall over with real users.
>
> Sam | 01:40
> Okay, decision: we keep Notion for the demo, and I'll evaluate a proper database next week. Postgres most likely.
