# Uncertainty Markers: Labels to Track the Strength of Claims
*September 2026*

In a strict sense, when an agent writes into a knowledge store, like an Obsidian Vault, it can either make the claim or not.  And we all know that Agents are often arrogant and will assert many things it assumes are facts.  That doesn't work for me as hallucinations carry the same weight as confirmed facts.  If it happens to be a more careful agent or model, it can also just decide not to write anything and thereby we will lose knowledge.  I want a system that works more like my own memory: some things I know are facts and I can tell you exactly where you can look them up, other things I am fairly certain of, but can't source.  And yet others are vague recollections I would want to confirm before I act on them. I want my agents to emulate a similar system.

Both of the original failures of the binary "to write or not to write" question compound errors when they are read into models and used to make decisions or write new memories. In other words, when notes are retrieved into prompts by search, summarized by scheduled jobs, and synthesized into new notes, an wrong claim does
not sit unread in one file: it is retrieved, quoted, and can even be strengthened into an even more outrageous claim, all the while each step makes it look more believable and better sourced than it ever was.

In this essay, I describe a small idiomatic categorization that Claude and I have adopted over the past three months to bound the certainty of claims it writes into the notes inside our Obsidian Vault.  Our personal markdown knowledge base, written to by both me and AI agents, required we impose an organizing principle for uncertainty after unverified claims kept arriving in notes and in the agent's memory files phrased exactly like the same as verified claims. This essay covers the syntax, the design decisions behind it, how it is enforced, how it helps and how it still doesn't, and how it relates to published work.

## The Language of Uncertainty

All claims on which a decision rests, even the most innocuous, are to be flagged in notes until they have been verified.  

The most uncertain flag is written the moment a claim is made without a verified source in hand:

`⚠ UNVERIFIED (YYYY-MM-DD) — <claim> — check: <one concrete step that would verify it>`

The resolution that replaces the flag **in place** is simply to verify it. The claim stays where it was in the vault but is now worded with certainty: it includes what the check found, and is followed by the verified marker:

`✓ VERIFIED (YYYY-MM-DD) — <how it was checked>`

The date records when the marker was written. It says nothing about when the claim was shown to be true. Currently, a flag with no date is a *legacy* artifact as it predates the full development of our syntax; legacy flags maintain their character and are counted separately from the newer ones.  Nothing has been rewritten in bulk.

If a check shows the claim to be wrong, the claim is corrected or deleted, and the correction is recorded in
the note that caused the error. This way, knowledge is never just lost.  There is no separate marker for a  claim that turned out false. Outside of the vault notes, like in MEMORY.md, false claims are deleted outright and its correction recorded
in a vault note.  The behavior results from the fact that memory files are loaded into every session, and a superseded line in one incurs the context cost in every session.

A partner convention marks a known gap in code or an equation, rather than in writing. It applies to a claim of limited veracity that we decided to ship knowingly:

`# ⚠ SHORTCUT (YYYY-MM-DD) — <what> — ceiling: <limit> — exit: <what lifts it>`

It is resolved the same way as an `⚠ UNVERIFIED` claim, i.e. by replacing it in place when the facts prevail. The scanner described below reads only markdown, meaning the vault notes and the agent's memory files (both of which are memories of a sort; I admit the word "memory" is doing a great deal of work in this essay), so it never sees a shortcut written in code. For those, `grep -rn '⚠ SHORTCUT'` serves as the ledger.

## The Life of an Uncertainty Flag

Here we give a synthetic example. On March 2, a note records something read in passing, worded as tentatively as it is known:

`⚠ UNVERIFIED (2026-03-02) — the nightly export may retry three times before it gives up; a code comment says three, and the code was not read — check: read the retry constant in the export job's configuration`

A week later, when vault audit is read, the flag is replaced, on its own line, by the claim as found and its resolution. Nothing else is added to the memory:

`The nightly export retries three times before it gives up. ✓ VERIFIED (2026-03-09) — read MAX_RETRIES = 3 in the export job's configuration at commit 4e1f0a2`

Had the constant been five, the sentence would have been updated to say five, and the resolution would have noted the source of the verified claim. In a knowledge base kept under version control, both outcomes are seen as a one-line diff that can be reviewed.  A search for the claim returns its status in the same result.

A shortcut in code looks like this:

`# ⚠ SHORTCUT (2026-03-02) — markers are matched line by line — ceiling: a marker split across a line wrap is missed — exit: parse by paragraph instead of by line`

## Six Decisions Worth a Word

**A binary flag, with no confidence score.** We considered and rejected a numeric confidence score, chiefly because a number invites quiet adjudication that no lint can catch: 0.7 drifting to 0.8 across two edits leaves less clear trace and how do we gauge confidence anyway?  AI tends frequently to be overconfident in my experience so most claims it makes would be scored higher than a human likely would (except, of course, arrogant people). On the other hand, when `⚠ UNVERIFIED` becomes `✓ VERIFIED` the result is a diff a person can easily read. As noted before, a number would also need calibrating, and maintaining the calibration over time and with a limited context window would be unwieldy.  Thus, binary status plus a date, a statement of how the claim was checked, and the check step carries everything a reader needs.

**A flag is resolved in place, on its own line.** The status of a claim lives on the same line as the
claim itself; thus, anyone who searches for the claim finds its status in the same result. A separate ledger
of resolutions would oblige the reader to join two files by hand, and in my experience that is a join almost no one bothers to make, myself included. It should also be noted that a verbatim copy of the line, whether into a summary, a quotation, or
another note, bears the status along with it.

**The check step is expected but not mandatory.** The scanner counts the flags that lack a `check:` clause,
and the weekly triage proposes a step for each of them; however, no flag is ever rejected for being
incomplete. The alternative fails toward suppression. A writer, human or agent, who cannot think of a check step and is confronted with a gate is, I suspect, more likely to delete the claim than to flag it, and the doubt would vanish along with the claim.

**A legacy class in lieu of a migration.** Undated flags are kept in a bucket of their own. They are triaged
a few at a time, each with a proposed replacement line, and they are never rewritten without notice. A bulk
rewrite would stamp today's date on claims made months earlier, thereby erasing the information the date exists to convey.

**Only bare occurrences are counted, and code spans are exempt.** A note that documents the convention must
be able to name a marker without asserting one. For that reason, the scanner strips inline code spans first,
so that a marker inside backticks is treated as a mention and never as a flag. That being said, code spans
alone did not suffice: the health report the scanner writes quotes flagged lines verbatim, outside of
backticks, and at one point it counted itself. The scanner therefore also excludes its own report by name.
The implementation strips inline spans but not fenced code blocks; for that reason, every example herein is
written as inline code.

**Each marker is a single string literal, and the scanner accepts no variants.** The scanner matches the
precise strings the writers are told to emit, instead of a pattern that tolerates variations in spelling;
hence, what is counted cannot drift away from what is written. The cost of this choice is that a misspelled
marker is simply not counted, and consequently both the writers' instructions and the write-time reminder bear the precise strings. In that sense the markers behave as idioms do: their meaning is agreed upon and holds only in the fixed form, much as "kick the bucket" stops meaning anything in particular once it becomes "kick the pail".

## How It Is Enforced, in Three Layers

**A reminder at the moment of writing.** A hook runs before each call the agent makes to its file-writing
and file-editing tools. In our setup it is a `PreToolUse` hook in Claude Code, matched to the `Write` and
`Edit` tools. It fires only for markdown files inside the vault or the agent's memory store, and it always
allows the call, attaching the syntax as a reminder instead of asking permission or refusing. Its purpose is to put the rule in front of the model at the moment of the write; my working theory is that instructions read once at the start of a session have to compete with everything read afterwards. The hook cannot judge whether a claim
ought to be flagged, and it makes no attempt to do so. Any exception raised inside the hook is handled and
the hook exits normally, because a bug in a reminder must never block a legitimate write.

**An offline scanner that classifies, and does more than count.** The scanner walks every markdown file
beneath a root directory and sorts each marker into one of three classes, as parsed from their syntax:

| Class | What the line contains |
|---|---|
| open | `⚠ UNVERIFIED` followed by a parenthesized date |
| legacy | `⚠ UNVERIFIED` with no date |
| resolved | `✓ VERIFIED`, dated or not |

For each marker, the scanner records the date, whether a `check:` clause is present, the file, the line
number, and the line verbatim. It never edits a note.

**A weekly triage with caps.** A scheduled job runs the scanner, writes a health report, and proposes work
without performing any of it. The proposals consist of a verification queue of a few open flags per week that
lack a check step, ranked first by age and then by how many flags a file contains, together with a legacy
triage of a few more, each with its replacement line written out for copy and paste. The report states how
many items were left out of the queue, so that the list is never truncated without notice. The caps keep the backlog reviewable; without them, I suspect it would soon become a wall I would stop reading. The agent's memory store is
scanned and reported under a heading of its own, since its corrections follow the different route described
previously.

The scanner also appends the counts from each run to a history file, so that what is reported is a trend
over time instead of a single snapshot.

## Where It Still Falls Short

**It is not a quality score.** The ratio of open to resolved markers mixes a flag written this morning with
one written months ago, and a note no one has needed since with one in daily use. The trend over time is, I think, the only part that means much.

**It does not cover every write.** The reminder is matched to two named tools. A write made through a shell
command, or through any other tool, never triggers it; the weekly scan finds the result later, although not
at the moment of writing.

**Its effect has not been measured.** The write-time hook keeps no log of its own firings, so there is
presently no way to say how often it changed what was written. A hook that only warns, and that keeps no log
of its warnings, cannot be evaluated, and this is, as far as I can tell, the convention's most obvious shortcoming. The
fault is mine: we built the reminder on July 31, weeks before I adopted the rule that every warning hook keep
a log of what it says, and I have yet to go back and give it one.

**It cannot flag doubt that no one felt.** No part of this verifies a claim, and a writer can assert a
falsehood with no marker whatsoever. It would be pleasant to claim that the convention makes a writer more careful; in truth, it only renders visible the doubt a writer actually had.

**It is not a dependable signal to downstream agents.** Automated read-back is the reason the marker exists: a flag travels with its claim into search results, summaries, and syntheses, where a person reviewing
the output can see it and a scanner can count it. Whether an agent that reads the flag actually discounts the
claim is a separate question, and the published evidence is discouraging. Kwon (discussed under Related Work)
found that a passive "unverified" tag was ignored, and that agents respond to how confidently a claim is
worded. Where agents read the notes, that evidence suggests it is wiser to word an unverified claim tentatively in addition to flagging it, preferring a modal hedge such as "may" to an attribution such as "reportedly", the
latter being the hedge the same study found agents discounted least. The convention does not require this;
however, the example given earlier follows it.

## Related Work

The search behind this section was conducted in two passes on September 29, 2026. The first pass covered
encyclopedia maintenance templates, code annotation conventions, note-taking communities, documentation and
knowledge-base tools, and recent work on LLM grounding and agent memory; the second covered engineering
requirements practice, intelligence analysis, legal citators, provenance standards, and laboratory notebooks.
Every source below was accessed that day. Each piece of this idiomatic system has a published precedent somewhere
below: engineering requirements attach a closure plan to an unconfirmed value, Wikipedia dates its tags, and
an agent-metadata format stores a re-runnable check with each verified claim. What no source was found to
combine is the particular set: a binary flag the writer places inline, on the claim's own line, at the moment
of writing; the date of writing in lieu of a deadline; a resolution that replaces the flag in place and
records the procedure used; and a legacy class in place of backfilled dates. That is a narrower claim than I would have
liked to make, and the relatives discussed below are closer than the word "novel" would suggest.

**Wikipedia's dated maintenance templates** are the closest relative I found to the form of these markers.
[`{{Citation needed}}`](https://en.wikipedia.org/wiki/Template:Citation_needed) is claim-level, inline,
machine-readable, and dated to the month, and the date sorts articles into dated maintenance categories so
that the oldest problems can be addressed first. A bot adds the date soon after an undated tag is placed.
Resolution removes the tag and adds a citation, whose
[`access-date`](https://en.wikipedia.org/wiki/Template:Cite_web) field records when the source was read. The
differences are threefold. First, the tag is designed for statements already in an article that lack a
source, so it typically serves as a reader's request to the writer, whereas this convention is the writer's own admission at the moment of writing. Second, the tag's optional `reason` describes the doubt but does not name
the step that would dispel it. Finally, a citation has a slot for a publication but none for evidence that is
a procedure, such as a query that was run or a file read at a given commit. The bot's dating is appropriate
for Wikipedia, because the bot runs soon after the tag is placed; a flag that predates a convention by months
has no such proxy, and so the convention keeps a legacy class instead.

**Engineering requirements practice** offers the closest relative I found to the check step, which, as an aerospace engineer, I probably ought to have remembered before the search began. NASA's systems
engineering guidance on
[writing requirements](https://www.nasa.gov/reference/appendix-c-how-to-write-a-good-requirement/) asks that
a value not yet settled be written as a best estimate marked "To Be Resolved" (TBR), together with its
rationale, what should be done to eliminate the TBR, who is responsible for doing so, and by when, and that a
complete listing of TBDs and TBRs be maintained with the requirements. That is, in effect, a claim-level flag
with a closure plan, which is most of the open form described herein. It differs in three respects: a TBR
bears an owner and a deadline where these markers bear the date the flag was written; closure is tracked in a
separate listing; and the document does not record how the value was finally confirmed.

**Code annotation conventions** are the closest relatives I found to `⚠ SHORTCUT`, which is largely established
practice with a single field added.
[Google's C++ style guide](https://google.github.io/styleguide/cppguide.html#TODO_Comments) reserves `TODO`
for code that is "temporary, a short-term solution, or good-enough but not perfect", names an owner or a bug,
and asks for a specific date or event for removal; the `exit:` field holds much the same thing. What the shortcut
form adds is `ceiling:`, the limit the shortcut imposes, and the date of writing it shares with the claim
markers. [PEP 350](https://peps.python.org/pep-0350/) (2005, rejected) proposed codetags with an originator,
an origination date, and a due date, and recorded completed items in a separate DONE file, which is the separate-log design this convention rejects. The `expiring-todo-comments` rule in
[eslint-plugin-unicorn](https://github.com/sindresorhus/eslint-plugin-unicorn/blob/main/docs/rules/expiring-todo-comments.md)
and the [todo_or_die](https://github.com/searls/todo_or_die) gem go further than an exit written in words, by
making the exit a machine-checked date, version, or dependency condition that fails the lint or raises an
error once it is met; where an exit can be stated in that manner, I would prefer their approach to mine. Software-engineering
research refers to such comments as self-admitted technical debt
([Potdar and Shihab, ICSME 2014](https://doi.org/10.1109/ICSME.2014.31)), and the shortcut form is a
structured instance thereof.

**Epistemic headers** state confidence for a document as a whole. LessWrong's
["epistemic status"](https://www.lesswrong.com/posts/Hrm59GdN2yDPWbtrd/feature-idea-epistemic-status),
proposed in 2018 as a per-post field, and the status, confidence, and importance metadata on
[gwern.net](https://gwern.net/about), graded with Kesselman's estimative words, both describe the author's
stance toward an entire essay. Neither is resolved over time, and both are graded, whereas this convention is per-claim, dated, and binary by design. The two are complementary: a header tells the reader how heavily to
lean on a piece, and the markers tell the reader which of its sentences were checked.

**Note-taking communities** mark the strength of claims with tags. The Zettelkasten
[evidence scale](https://zettelkasten.de/posts/strength-claim/) (2022) grades individual claims from anecdote
to cross-checked primary source, and a
[forum thread on unverified claims](https://forum.zettelkasten.de/discussion/2960/how-to-handle-unverified-indirect-claims)
(2024) collects ad hoc markers such as `#check_source` tags, to-do checkboxes, and claims restated as
questions. Not one of these is dated, bears a check step, or retains a record once it is resolved.

**Grading and status schemes** in other fields rate how far a source or a statement may be trusted. The
[Admiralty code](https://en.wikipedia.org/wiki/Admiralty_code) grades an intelligence report on two scales,
the reliability of its source and the credibility of its information, and the US intelligence community's
[ICD 203](https://www.dni.gov/files/documents/ICD/ICD-203.pdf) asks analysts to state both the likelihood of a
judgment and their confidence in its basis. Both schemes are graded, where these markers are binary, and both
describe an assessment instead of a pending check. Legal citators such as KeyCite and Shepard's
[flag cases](https://guides.libraries.uc.edu/c.php?g=222559&p=1472876) that are no longer good law; that
status is maintained by the vendor, and the writer who cites the case plays no part in it. Wikidata's
[deprecated rank](https://www.wikidata.org/wiki/Help:Ranking) keeps a statement known to be wrong visible,
with a qualifier giving the reason, whereas this convention corrects or deletes the claim and records the
correction.

**Knowledge-base products and decision records** operate at the level of the document.
[Guru](https://www.getguru.com/features/verification) gives each card a verified or unverified status, a
verifier, and an interval after which the card lapses back to unverified; the unit is the card, the trigger is
elapsed time, and verification is an attestation instead of a recorded method.
[Architecture decision records](https://www.cognitect.com/blog/2011/11/15/documenting-architecture-decisions)
(Nygard, 2011) bear a status of proposed, accepted, deprecated, or superseded, and they keep superseded
records visible in lieu of deleting them, which reflects the same instinct as the legacy class, applied to
decisions and not to factual claims.

**LLM verification methods** check claims at the time of generation.
[Chain-of-Verification](https://arxiv.org/abs/2309.11495) (Dhuliawala et al., 2023) has a model draft an
answer, plan verification questions, answer them independently, and then revise; the questions resemble a
check step, but they serve the single response being produced and not a later reader.
[Self-RAG](https://arxiv.org/abs/2310.11511) (Asai et al., 2023) trains a model to emit reflection tokens,
among them one judging whether a passage supports what was generated. These are signals inside a generation;
no durable record remains in a store for a person to audit afterwards.

**Agent memory work** comes nearest in purpose, as far as I can judge. GitHub's
[agentic memory for Copilot](https://github.blog/ai-and-ml/github-copilot/building-an-agentic-memory-system-for-github-copilot/)
(January 2026) stores each remembered fact with citations to code locations, and the agent re-reads them
before relying on the fact. That is automatic re-verification, and it works because the evidence is code the
agent can re-read; many claims in a personal knowledge base rest on evidence that cannot be re-read
mechanically, and so this convention keeps the unverified state visible instead of making verification a
prerequisite for use. [AKF](https://github.com/HMAKT99/AKF) (Agent Knowledge Format, 2026) goes further on
the agent side: it embeds metadata in a file listing claims, each with a verified flag, a trust score between
0 and 1, and timestamped evidence, and a stamp can bear a re-runnable probe, so that a later agent re-checks
the claim instead of trusting the label; a file modified after its stamp is reported as stale. That record
holds nearly everything a resolution here holds, plus a stored check. It differs in residing as
machine-readable metadata about a file, where these markers are text on the claim's own line; in scoring
trust numerically; and in targeting artifacts an agent can re-test, where these markers target claims a person reads. Two recent papers bear on the marker directly.
[Kwon (2026)](https://arxiv.org/abs/2606.29279) finds that memory consolidation turns hedged remarks into
confident stored facts, that agents respond to the confidence of the phrasing and not to its source, and that
a passive "unverified" tag is ignored, with evidential phrasing such as "reportedly" discounted least of all
hedges; its recommended remedy is to keep the tentative phrasing in the store. An open flag is, I have to admit, just such a separable tag; thus, the finding limits what the marker can do for an agent reader, and it is the origin of
the aforementioned advice on wording. [Hu (2026)](https://arxiv.org/abs/2609.20211) shows that summarizers
frequently weaken, and memory compressors often remove, the framing that marks a claim as unverified, and
recommends carrying that status as structured state attached to the claim. A single, exact marker on the
claim's line is a modest step in that direction, although a summarizer can still drop it.

## Adopting It Elsewhere

If I were to set this up again somewhere else, these are the four pieces I would start with, in the order in which I think they pay off:

1. The two claim markers and the in-place resolution rule, written down wherever writers, human or agent,
   read their instructions.
2. A scanner that classifies markers by their syntax, exempts code spans, and excludes its own report.
3. A write-time reminder that allows the write and reminds the writer, instead of gating it.
4. A weekly pass that proposes capped fixes, ready for copy and paste, and edits no note itself.

I suspect the first piece alone provides most of the value. The fourth is what prevents the first from decaying into a
field that no one resolves. The best way I have found to tell whether it is working is to run the scanner on a schedule and follow two numbers over time: resolved markers against open ones, and open flags that lack a check step.

---

Drafted with Claude from my design and notes; edited by me.

© 2026 Nathan Mundis. Licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
