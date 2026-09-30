# Certainty markers: a grammar for claims nobody has checked yet

*September 2026*

An agent that writes into a knowledge base has two bad options when it is not sure of something. It can
assert the claim anyway, in which case the note carries a wrong fact with the same authority as a right one.
Or it can drop the claim, in which case a later reader cannot tell a thing that was checked and found false
from a thing that was never looked at, or from a thing nobody thought of.

Both failures get worse when the knowledge base is read back automatically. When notes are retrieved into
prompts by search, summarized by scheduled jobs, and synthesized into new notes, an unmarked wrong claim does
not sit unread in one file: it is retrieved, quoted, and built on, and each step makes it look better
sourced than it was.

This essay describes a small grammar that was adopted for exactly that setting, a personal markdown
knowledge base written to by both a person and a coding agent, after unverified claims kept arriving in notes
and in the agent's memory files phrased exactly like checked ones. It covers the grammar, the design
decisions behind it, how it is enforced, what it does not give you, and how it relates to published work.

## The grammar

Two forms for prose, and nothing else.

An open flag, written the moment a claim is made without a source in hand:

`⚠ UNVERIFIED (YYYY-MM-DD) — <claim> — check: <one concrete step that would verify it>`

A resolution, which replaces the flag **in place**. The claim stays where it was, now worded as what the
check found, and is followed by:

`✓ VERIFIED (YYYY-MM-DD) — <how it was checked>`

The date records when the marker was written. It says nothing about when the claim became true. A flag with
no date is *legacy*, meaning it predates the grammar; legacy flags stay valid and are counted separately
rather than being rewritten in bulk.

If a check shows the claim to be wrong, the claim is corrected or deleted, and the correction is recorded in
the note that caused the error. A resolved marker never stands over a claim that turned out false. The
agent's memory files are handled differently: a wrong memory is deleted outright and its correction recorded
in a knowledge-base note, because memory files are loaded into every session, and a superseded line there
costs context in all of them.

A sibling convention marks a known gap in code rather than in prose, for a limit shipped knowingly:

`# ⚠ SHORTCUT (YYYY-MM-DD) — <what> — ceiling: <limit> — exit: <what lifts it>`

It is resolved the same way, by replacing it in place when the exit is taken. The scanner described below
does not read it; `grep -rn '⚠ SHORTCUT'` is its whole ledger, by design.

## One flag's life

A synthetic example. On 2 March a note records something read in passing, worded as tentatively as it is
known:

`⚠ UNVERIFIED (2026-03-02) — the nightly export may retry three times before it gives up; a code comment says three, and the code was not read — check: read the retry constant in the export job's configuration`

A week later someone runs the check. The flag is replaced, on its own line, by the claim as found and its
resolution, and nothing is added anywhere else:

`The nightly export retries three times before it gives up. ✓ VERIFIED (2026-03-09) — read MAX_RETRIES = 3 in the export job's configuration at commit 4e1f0a2`

Had the constant been 5, the sentence would have said five, and the resolution would have said what was
read. In a knowledge base kept under version control, either outcome is a one-line diff that a person can
review, and a search for the claim returns its status in the same result.

A shortcut in code looks like this:

`# ⚠ SHORTCUT (2026-03-02) — markers are matched line by line — ceiling: a marker split across a line wrap is missed — exit: parse by paragraph instead of by line`

## Six decisions worth defending

**A binary flag, with no confidence score.** Numeric confidence was considered and rejected, chiefly because
a number invites quiet re-adjudication that no lint can catch: 0.7 drifting to 0.8 across two edits leaves no
trace, whereas `⚠ UNVERIFIED` becoming `✓ VERIFIED` is a diff a person can read. A number would also need
calibrating, and nothing in this setup could measure whether it was. Binary status plus a date, a statement
of how the claim was checked, and a check step carries what a reader needs.

**Resolution happens in place, rather than in a separate log.** The status lives on the same line as the
claim, so anyone who searches for the claim gets its status in the same result. A separate ledger of
resolutions would require the reader to join two files by hand, and that is the join nobody does. It also
means a verbatim copy of the line (into a summary, a quotation, or another note) carries the status with it.

**The check step is expected without being mandatory.** The scanner counts flags that lack a `check:`
clause, and the weekly triage proposes one for them, but nothing rejects a flag for being incomplete. The
alternative fails toward suppression: a writer that cannot think of a check step, facing a gate, deletes the
claim instead of flagging it, and the doubt disappears along with the claim.

**A legacy class instead of a migration.** Undated flags form a separate bucket. They are triaged a few at a
time, each with a proposed replacement line, and are never silently rewritten. A bulk rewrite would stamp
today's date on claims made months earlier, which destroys exactly the information the date exists to carry.

**Bare occurrences only; code spans are exempt.** A note that documents the convention has to be able to
name a marker without asserting one. The scanner strips inline code spans first, so a marker inside
backticks counts as a mention and never as a flag. Code spans alone were not enough, though: the health report the scanner
writes quotes flagged lines verbatim, outside backticks, and it once counted itself, so the scanner also
excludes its own report by name. The implementation strips inline spans but not fenced code blocks, which is
why every example in this essay is written as inline code.

**Each marker is one string literal, and the scanner accepts no variants.** The scanner matches the exact
strings the writers are told to emit, rather than a pattern that tolerates spelling drift, so what gets
counted cannot drift from what gets written. The cost is that a misspelled marker is simply not counted,
so the writers' instructions and the write-time reminder both carry the exact strings.

## How it is enforced, in three layers

**A write-time reminder that cannot judge, and does not pretend to.** A hook runs before each call to the
agent's file-writing and file-editing tools; in this setup it is a `PreToolUse` hook in Claude Code, matched
to the `Write` and `Edit` tools. It fires only for markdown files inside the knowledge base or the agent's
memory store, and it always allows the call, attaching the grammar as a reminder rather than asking or
refusing. Its whole job is to put the rule in front of the model at the moment of the write, because
instructions read once at the start of a session compete with everything read since. Any exception inside
the hook exits cleanly, since a bug in a reminder must never block a legitimate write.

**An offline scanner that classifies rather than counts.** The scanner walks every markdown file under a
root and sorts each marker into one of three classes, parsed from the grammar:

| Class | What the line carries |
|---|---|
| open | `⚠ UNVERIFIED` followed by a parenthesized date |
| legacy | `⚠ UNVERIFIED` with no date |
| resolved | `✓ VERIFIED`, dated or not |

For each marker it records the date, whether a `check:` clause is present, the file, the line number, and
the line verbatim. It never edits a note.

**A weekly triage with caps.** A scheduled job runs the scanner, writes a health report, and proposes work
without doing any: a verification queue of a few open flags a week that lack a check step, ranked oldest
first and then by how many flags a file carries, and a legacy triage of a few more with the replacement line
written out for copy and paste. It states how many items it left unqueued rather than truncating silently.
The caps keep the backlog reviewable instead of a wall. The agent's memory store is scanned and reported
under its own heading, because its corrections take the different route described above.

The scanner also appends each run's counts to a history file, so what gets reported is a trend rather than
a snapshot.

## What this does not give you

**A quality score.** The ratio of open to resolved markers mixes a flag written this morning with one
written months ago, and a note nobody has needed since with one in daily use. Only the trend means much.

**Coverage of every write.** The reminder is matched to two named tools. A write made through a shell
command, or through any other tool, never sees it; the weekly scan finds the result later, but not at the
moment of writing.

**A measured effect for the reminder.** The write-time hook keeps no log of its own firings, so there is no
way to say how often it changed what got written. A warn-only hook that keeps no log of its warnings cannot
be evaluated, and that is the convention's plainest gap.

**Protection from doubt nobody felt.** Nothing here verifies a claim, and a writer can assert a falsehood
with no marker at all. The grammar buys visibility for the doubt a writer actually had.

**A dependable signal to downstream agents.** Automated read-back is the reason the marker exists: a flag
travels with its claim into search results, summaries, and syntheses, where a person reviewing the output can
see it and a scanner can count it. Whether an agent that reads the flag actually discounts the claim is a
separate question, and the published evidence is discouraging. Kwon (under related work) found that a
passive "unverified" tag was ignored, and that agents respond to how confidently a claim is worded. Where
agents read the notes, the useful addition is to word an unverified claim tentatively as well as flagging
it, preferring a modal hedge such as "may" over attribution such as "reportedly", which the same study found
agents discounted least. The grammar does not require this; the example above follows it.

## Related work

The search behind this section was run in two passes on 29 September 2026. The first covered encyclopedia
maintenance templates, code annotation conventions, note-taking communities, documentation and
knowledge-base tools, and recent work on LLM grounding and agent memory; the second covered engineering
requirements practice, intelligence analysis, legal citators, provenance standards, and laboratory
notebooks. Every source below was accessed that day. Each piece of this grammar has a published precedent
somewhere below: engineering requirements attach a closure plan to an unconfirmed value, Wikipedia dates its
tags, and an agent-metadata format stores a re-runnable check with each verified claim. What no source found
combines is the particular set: a binary flag the writer places inline, on the claim's own line, at the
moment of writing; a written-on date rather than a deadline; a resolution that replaces the flag in place and
records the procedure used; and a legacy class in place of backfilled dates. That is a narrow claim, and the
relatives below are closer than the word "novel" would suggest.

**Wikipedia's dated maintenance templates** are the closest relative for the form of the prose markers.
[`{{Citation needed}}`](https://en.wikipedia.org/wiki/Template:Citation_needed) is claim-level, inline,
machine-readable, and dated to the month, and the date sorts articles into dated maintenance categories so
the oldest problems can be worked first. A bot adds the date soon after an undated tag is placed. Resolution
removes the tag and adds a citation, whose
[`access-date`](https://en.wikipedia.org/wiki/Template:Cite_web) field records when the source was read. The
differences: the tag is designed for statements already in an article that lack a source, so it typically
works as a reader's request to the writer, while this grammar is the writer's own admission at the moment of
writing; its optional `reason` describes the doubt and says nothing of the step that would clear it; and a citation has a slot
for a publication but not for evidence that is a procedure, such as a query that was run or a file read at a
commit. The bot's dating is right for Wikipedia, because it runs soon after the tag is placed; a flag that
predates a convention by months has no such proxy, so the grammar keeps a legacy class instead.

**Engineering requirements practice** has the closest relative for the check step. NASA's systems
engineering guidance on
[writing requirements](https://www.nasa.gov/reference/appendix-c-how-to-write-a-good-requirement/) asks that
a value not yet settled be written as a best estimate marked "To Be Resolved" (TBR), together with its
rationale, what should be done to eliminate the TBR, who is responsible, and by when, and that a complete
listing of TBDs and TBRs be kept with the requirements. That is a claim-level flag with a closure plan, which
is most of the open form here. The differences are that a TBR carries an owner and a deadline where this
grammar carries the date the flag was written, that closure is tracked in a separate listing, and that
nothing records in the document how the value was finally confirmed.

**Code annotation conventions** are the closest relatives for `⚠ SHORTCUT`, which is mostly established
practice with one field added.
[Google's C++ style guide](https://google.github.io/styleguide/cppguide.html#TODO_Comments) reserves `TODO`
for code that is "temporary, a short-term solution, or good-enough but not perfect", names an owner or a bug,
and asks for a specific date or event for removal; the `exit:` field holds exactly that. What the shortcut
form adds is `ceiling:`, the limit the shortcut imposes, and the written-on date shared with the prose
markers. [PEP 350](https://peps.python.org/pep-0350/) (2005, rejected) proposed codetags with an originator,
an origination date, and a due date, and recorded completed items in a separate DONE file, the separate-log
design this grammar rejects. The `expiring-todo-comments` rule in
[eslint-plugin-unicorn](https://github.com/sindresorhus/eslint-plugin-unicorn/blob/main/docs/rules/expiring-todo-comments.md)
and the [todo_or_die](https://github.com/searls/todo_or_die) gem go further than a prose exit, by
making the exit a machine-checked date, version, or dependency condition that fails the lint or raises once
it is met; where an exit can be stated that way, it should be. Software-engineering research calls these
comments self-admitted technical debt ([Potdar and Shihab, ICSME 2014](https://doi.org/10.1109/ICSME.2014.31)),
and the shortcut form is a structured instance of it.

**Epistemic headers** state confidence for a whole document. LessWrong's
["epistemic status"](https://www.lesswrong.com/posts/Hrm59GdN2yDPWbtrd/feature-idea-epistemic-status),
proposed in 2018 as a per-post field, and the status, confidence, and importance metadata on
[gwern.net](https://gwern.net/about), graded with Kesselman's estimative words, both describe the author's
stance toward a whole essay. Neither is resolved over time, and both are graded, where this grammar is
per-claim, dated, and deliberately binary. The two are complementary: a header says how hard to lean on a
piece, and markers say which of its sentences were checked.

**Note-taking communities** mark claim strength with tags. The Zettelkasten
[evidence scale](https://zettelkasten.de/posts/strength-claim/) (2022) grades individual claims from
anecdote to cross-checked primary source, and a
[forum thread on unverified claims](https://forum.zettelkasten.de/discussion/2960/how-to-handle-unverified-indirect-claims)
(2024) collects ad hoc markers such as `#check_source` tags, to-do checkboxes, and claims restated as
questions. None of these is dated, carries a check step, or leaves a record when it is resolved.

**Grading and status schemes** in other fields rate how far to trust a source or a statement. The
[Admiralty code](https://en.wikipedia.org/wiki/Admiralty_code) grades an intelligence report on two scales,
the reliability of its source and the credibility of the information, and the US intelligence community's
[ICD 203](https://www.dni.gov/files/documents/ICD/ICD-203.pdf) asks analysts to state both the likelihood of a
judgment and their confidence in its basis. Both are graded rather than binary and describe an assessment
rather than a pending check. Legal citators such as KeyCite and Shepard's
[flag cases](https://guides.libraries.uc.edu/c.php?g=222559&p=1472876) that are no longer good law; the
vendor maintains that status, and the writer who cites the case has no part in it. Wikidata's
[deprecated rank](https://www.wikidata.org/wiki/Help:Ranking) keeps a statement known to be wrong visible,
with a qualifier giving the reason, where this grammar corrects or deletes the claim and records the
correction.

**Knowledge-base products and decision records** work at the document level.
[Guru](https://www.getguru.com/features/verification) gives each card a verified or unverified status, a
verifier, and an interval after which the card lapses back to unverified; the unit is the card, the trigger is
elapsed time, and verification is an attestation rather than a recorded method.
[Architecture decision records](https://www.cognitect.com/blog/2011/11/15/documenting-architecture-decisions)
(Nygard, 2011) carry a status of proposed, accepted, deprecated, or superseded, and keep superseded records
visible rather than deleting them, which is the same instinct as the legacy class, applied to decisions
rather than to factual claims.

**LLM verification methods** check claims at generation time.
[Chain-of-Verification](https://arxiv.org/abs/2309.11495) (Dhuliawala et al., 2023) has a model draft an
answer, plan verification questions, answer them independently, and revise; the questions resemble a check
step, but they serve the one response being produced rather than a later reader.
[Self-RAG](https://arxiv.org/abs/2310.11511) (Asai et al., 2023) trains a model to emit reflection tokens,
among them one judging whether a passage supports what was generated. These are signals inside a generation;
nothing durable is left in a store for a person to audit later.

**Agent memory work** is the nearest in purpose. GitHub's
[agentic memory for Copilot](https://github.blog/ai-and-ml/github-copilot/building-an-agentic-memory-system-for-github-copilot/)
(January 2026) stores each remembered fact with citations to code locations, and the agent re-reads them
before relying on the fact. That is automatic re-verification, and it works because the evidence is code
the agent can re-read; many claims in a personal knowledge base rest on evidence that cannot be re-read
mechanically, so this grammar keeps the unverified state visible instead of making verification a
precondition for use. [AKF](https://github.com/HMAKT99/AKF) (Agent Knowledge Format, 2026) goes further on
the agent side: it embeds metadata in a file listing claims, each with a verified flag, a 0 to 1 trust score,
and timestamped evidence, and a stamp can carry a re-runnable probe, so a later agent re-checks the claim
instead of trusting the label; a file modified after its stamp reads as stale. That record holds nearly
everything this grammar's resolution holds, plus a stored check. It differs in living as machine-readable
metadata about a file rather than as text on the claim's own line, in scoring trust numerically, and in
targeting artifacts an agent can re-test rather than prose claims a person reads. Two recent papers bear on
the marker directly.
[Kwon (2026)](https://arxiv.org/abs/2606.29279) finds that memory consolidation turns hedged remarks into
confident stored facts, that agents respond to the confidence of the phrasing rather than to its source, and
that a passive "unverified" tag is ignored, with evidential phrasing such as "reportedly" discounted least of
all hedges; its recommended fix is to keep the tentative phrasing in the store. An open flag is exactly such
a separable tag, so the finding limits what the marker can do for an agent reader, and it is the source of
the advice above on wording.
[Hu (2026)](https://arxiv.org/abs/2609.20211) shows that summarizers frequently weaken, and memory
compressors often remove, the framing that marks a claim as unverified, and
recommends carrying that status as structured state attached to the claim. A single exact marker on the
claim's line is a small step in that direction, though a summarizer can still drop it.

## Adopting it somewhere else

Four pieces, in the order they pay off:

1. The two prose markers and the in-place resolution rule, written down where writers (human or agent) read
   their instructions.
2. A scanner that classifies markers by the grammar, exempts code spans, and excludes its own report.
3. A write-time reminder that allows the write and reminds, rather than gating it.
4. A weekly pass that proposes capped, copy-pasteable fixes and edits nothing.

The first piece alone is most of the value. The fourth is what keeps the first from decaying into a field
nobody resolves. To see whether it is working, run the scanner on a schedule and watch two numbers over
time: resolved markers against open ones, and open flags that lack a check step.

---

Drafted with Claude from my design and notes; edited by me.

© 2026 Nathan Mundis. Licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
