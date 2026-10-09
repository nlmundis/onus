# The onus plan

This is the library's plan: what onus is for, the decisions that bind it, how its correctness is established,
and the order of work. It is the canonical copy. Amendments land here, dated, by pull request; a change that
contradicts a decision below is an amendment, not an edit. The projects that use onus (the adopters) are
planned outside this repository; this plan covers only what they need from the library.

The plan was written on 2026-09-23 and kept outside the repository until 2026-09-29, when its library sections
moved here. The progress log is `docs/handoffs/`.

## Purpose

Three problems, seen across the maintainer's own projects, motivate it:

- **Weak verdicts read as evidence.** A small comparison can have so little power that "not met" says almost
  nothing, and nothing on the page says so.
- **Peeking inflates error.** A one-sided sign test at a nominal 5% has an exact size of 0.0443 at 100
  non-tied pairs. Read at every 10 pairs up to 100, it rejects at least once under the null with probability
  0.1250 (`onus.stats.sequential_size(range(10, 101, 10), alpha="0.05", alternative="greater")`, against
  `[100]` for the single look).
- **Copies drift.** Three hand-written sign and binomial tests in those projects disagreed on sidedness.

onus answers them with one small, public, dependency-free library:

- **Exact, hard-to-misuse statistical tests**, with pre-registration records that fix a rule before its data.
- **Property-based testing** (Hypothesis) that is deterministic inside the gate.
- **Two-tier approval testing:** tier 1 baselines that a working session may re-record, where the pull
  request diff is the review; and tier 2 sign-offs, for ground truth, that only a person makes from their own
  terminal.

**Nothing already read may move.** Code that produced a verdict someone has read is frozen and never calls
the library. The library serves new experiments, and an adopter proves parity with differential tests.

## Decisions (2026-09-23)

Numbered as when they were made; the gaps are decisions about the adopters, kept with them.

- **1. Both meanings of "hypothesis testing"** are in scope: statistical significance, and property-based
  testing with Hypothesis.
- **3. Hosting:** public on GitHub, MIT, pinned by git tag. Nothing goes to PyPI.
- **4. Two approval tiers.** Tier 1 (baseline) may be re-recorded by a session; tier 2 (sign-off) is the
  maintainer's alone, from their own terminal, as a hash-bound ledger line.
- **5. Live pre-registered rules are frozen.** A fix arrives as a dated amendment, recorded before the affected
  verdict is read.
- **6. The name** is `onus` (onus probandi: the claim carries its own proof). Its jobs are several, so each
  became a subpackage named by intent (see Shape).
- **8. The library is a runtime dependency for new experiments** only. Frozen legacy functions stay untouched.
- **9. Tier-2 hardening:** the library's tripwires, plus a control outside the library that keeps agent
  sessions from making sign-offs (step H). Signed ledger lines and a ledger mirror were declined for now.

## Amendment 1 (2026-09-29): prereg v0.1 defaults

The maintainer ratified the five defaults that `onus.prereg` (PR #5) chose, and left the count-horizon gap
below open for L1 step 4; the open item's wording came from an adversarial review of this plan, which the
maintainer approved. Each default binds v0.1 and is revisited only by a later dated amendment:

- **`cluster_key` must be null.** `load` refuses any other value until v0.2 adds `cluster`, because v0.1
  `evaluate` treats every unit as independent and would silently ignore a declared cluster, giving
  anti-conservative p-values.
- **`looks` must be `[horizon]`.** No interim reads; sequential helpers stay out of scope, and `status`
  reports "pending" before the horizon without a p-value. For a days horizon, `evaluate` trusts the caller's
  `as_of`; Amendment 2, D5 decides how an early read is recorded, and is built with `report`.
- **Each hypothesis states `method`.** v0.1 accepts only `"exact"`. The method is fixed before the data
  because v0.2's `mann_whitney(method=...)` makes the choice change p.
- **A days horizon's window may not open before `registered`** (checked only against the record's own
  `registered` date).
- **`Rule` holds read-only mappings**, so it cannot be pickled or deep-copied. A dated amendment revisits this
  when the first adopter needs either.
- **Open, owner: the session that starts L1 step 4.** A count horizon has no equivalent check: `evaluate`
  takes the first N units by `order_key` with no date test, so they can predate registration. Decide whether
  to add a check (for example, a date-valued `order_key`, or a `start` for count horizons) or to disclose it
  as a limit, and decide it before the first adopter writes a count-horizon record; if that record comes
  first, its `provenance` discloses the gap. A check against `registered` alone only tests the record against
  itself, because the record's author types `registered`, so the decision names what witnesses that date
  (for example, the tier-2 sign-off time).

## Amendment 2 (2026-09-29): report design (L1 step 3, part 2)

Options were drafted and checked by adversarial review against `f7a3c51` before the maintainer chose; the
review changed three of the recommendations (D1, D5, D7). Each choice binds v0.1:

- **D1, receipt binding: re-derive from the data.** `render(rule, data, name, *, receipt, reads_path,
  as_of=None)` runs `evaluate` itself. It requires a line in the caller-named reads file (equal to
  `receipt.reads_path` once resolved) whose sha256 is `receipt.line_sha256`, and whose prereg, experiment,
  data_sha256, n, labels, and at all match (and, since Amendment 3's third review, whose `early` is the one
  its `at` gives; E8). Every number in the sentence comes from the data in that call, so a hand-built receipt
  or a hand-edited `Evaluation` cannot be rendered. render does file I/O. Ship `receipt_from_line(reads_path,
  line_sha256)` so that a second process never hand-builds a receipt.
- **D2, MDE power: a fixed `Fraction(4, 5)`, printed** ("MDE at 80% power"). It is computed at the test's
  non-tied n (`TestResult.n`, not `Evaluation.n`), so it is conditional on the observed ties, and the sentence
  says so. With no rejection region, the sentence says "no outcome at this n can reach significance at level
  α". When α is so large that the test already has 80% power, it says "no MDE exists". The constant is frozen
  once released, because documents quote the sentences. An optional per-hypothesis `power` key defaulting to
  4/5 may be added later; it is additive.
- **D3, MDE alpha: α/m**, where m is counted from the rule's family, named in the sentence as a Bonferroni
  bound. With exact fractions, a raw p at or below α/m is met under Holm or Benjamini-Hochberg whatever the
  other members show, so this is a guaranteed floor on power. It is conservative: it overstates the MDE,
  loosely for BH and for large families.
- **D4, exploratory: `render_exploratory(result)`**, which accepts a `TestResult` only and raises TypeError on
  anything else. The sentence starts "Exploratory:" and carries sidedness, the null, ties, missing, method,
  warnings, the exact p, and the onus version. It has no met / not met, no significance, and no MDE, because
  there is no alpha. `render` always requires a receipt. Known gap: a pre-registered hypothesis's `.result`
  can still be printed this way unrecorded, as plain attribute access already allows.
- **D5, early read: record and flag.** `Evaluation` stores `as_of`. `record_read` always appends, and refuses a
  days-horizon `Evaluation` without `as_of`. Each line records `as_of` and `early`, which is true when the read
  time is before `horizon.end` 12:00 UTC, the moment the window has closed in every time zone. render states
  no met / not met for an early read and shows "read early", beside the post hoc label; Amendment 3 drops its MDE
  clause (E3), then all else about the result (E8), so it shows only when it was read and when the window closed,
  and, since Amendment 4's E12, that it was a re-read on different data when it was.
- **D6, re-read on different data: seal, with a recorded override.** `record_read` refuses a read whose
  data_sha256, n, or labels differ from an earlier read in the same reads file with the same experiment or
  record stem. It allows one only when `supersedes=<the first read's line sha256>` and `reason=` are passed,
  and writes both into the line; render then shows "re-read on different data; first read <hash>". The
  check-then-append takes a lock (flock), and a malformed earlier line refuses. The seal binds only the reads
  file it is given.
- **Schema:** the read line moves from `read/1` to `read/2`, carrying `as_of`, `early`, `supersedes`, and
  `reason`. No adopter reads file exists yet.
- **D7, `prereg_id`: keep the stem.** No code change.
- **D8, the read time (decided after the review raised it): `record_read` loses `now=`.** It reads the clock
  through one private function that tests patch, so the recorded time, and with it `early` (D5), is not the
  caller's to choose. This changes `record_read`'s merged but unreleased signature; the test that pins the
  exact line compares every field but `at`, and checks that `at` lies between two clock reads.

## Amendment 3 (2026-09-29, extended 2026-09-30): report details

The review of `report` left three questions the spec did not decide (its findings F3, F6, and F7's case half),
and the build left three more; the maintainer chose each from options. Each choice binds v0.1. A second review,
of what these choices built, found where the build fell short of them; the notes marked "as built" record the
result. On 2026-09-30 the maintainer answered what that review left open, as E7 to E10. A third review, of that build,
found where E9's read, E1's reading of an id, and render's check of an early read fell short; its fixes are
marked "as built" too:

- **E1, `assert_quoted`: every copy must match (F3).** Withdrawn from this step by Amendment 4's E11, apart
  from the one-line rule, which stands; kept here as the record of what three reviews tried.
  `assert_quoted(doc, sentence)` takes the prereg id and
  the hypothesis name from the rendered sentence. Every line of the document that names both must hold the
  rendered sentence verbatim, after any markdown prefix such as "- " or "> ", and at least one such line must
  exist; otherwise it raises AssertionError naming the offending line. A stale copy of the same result on a line
  of its own therefore fails wherever it stands in the document, as does any other wording of it on one line
  with both. The sentence stays one line.
  - As built: `load` refuses a hypothesis name, family, or file stem holding any break `str.splitlines` makes
    (E10), and `render` refuses a sentence that would span lines as a second check; `assert_quoted` raises
    ValueError for one that does, and for a sentence `render` did not return (an empty or exploratory one).
  - As built, what "names" means: a line names the id or the name where it stands as a word, with no word
    character running on from either end, so "fast" is not named in "faster", nor `layout@X` in `old_layout@X`.
    Inside the body of any rendered sentence on the line, from its verdict to its onus version, only the prereg
    id that body names counts, since its other words are the template's, its family's, or its warnings'.
    Elsewhere on the line, the name does not count inside the prereg id, and since the third review an id that a
    rendered sentence in the document names is read whole, the longest first, with no name inside it. So a document
    quoting each sentence once passes when a hypothesis is named "warnings" or "power", when "fast" stands beside
    "faster", when the file stem is a hypothesis's name, and when `layout@X` stands beside `old_layout@X`, or
    beside `old-layout@X`, `old.layout@X`, or `old layout@X` with that record's sentence in the document. A
    document quoting both a read and the re-read that superseded it fails for each.
  - Known limits, from reading line by line: a line quoting another hypothesis of the same record whose name
    holds this one's as a word ("faster" in "much faster") fails too, as does prose naming `old-layout@X` (or
    any id holding this one after a character that is not a word character) when no sentence of that record
    stands in the document, since nothing there tells that id from prose followed by `layout@X`. A stale copy
    passes when it shares a line with the exact sentence, and when it is written inside the body of another
    sentence on its line. A stale copy hard-wrapped so that no one line names both passed too, until E9.
- **E2, MDE precision: the gap to 4 significant digits (F6).** The MDE prints as p0 plus the gap ("success
  probability 0.5 + 0.4635"; "0.999 - 0.001844" below the null), with p0 exact and the gap, the MDE's distance
  from p0, to 4 significant digits, rounded away from the null, so the printed effect still reaches 80% power;
  where those digits would print an effect outside [0, 1], E7 prints the exact gap instead. It replaces the 4
  fixed decimals, which at n = 4000 printed 1.0000 at p0 = 999/1000 (the MDE is 0.99994) and 0.0005 at
  p0 = 1/1000000 (the MDE is 0.000402). It pins sentences once released, as D2's constant does.
- **E3, early read: no verdict and no MDE.** An early read's sentence carries neither a verdict nor the MDE
  clause, so nothing hints at the result; the MDE appears only on a read that is not early and not met. The
  sentence still carried p and the family's adjusted p beside α, from which a reader could work the verdict out,
  until E8 withheld those and every other clause about the result.
- **E4, the seal after an override: kept as built.** After a recorded override, every later read that differs
  from the first read, a re-read of the corrected data included, needs `supersedes=` (the first read) and
  `reason=` again, and render keeps showing "re-read on different data; first read <hash>" on each. So does a
  read of the first data again, which differs from the re-read. No code change; a test and a mutant now pin the
  corrected data read again.
- **E5, `reads_path` equality: kept as built (F7's case half).** render compares the caller's `reads_path`
  with the receipt's once both are resolved (D1), and `resolve()` keeps a name's spelling, so on a
  case-insensitive disk "Reads.jsonl" is refused for "reads.jsonl", as is a hard link, which a file-identity
  check would have accepted. No code change; a test and a mutant now pin both refusals.
- **E6, Windows: `fcntl` is imported lazily.** `record_read` imports fcntl itself, so `onus.prereg` and
  `onus.report` import on every platform. On a platform without fcntl, `record_read` raises NotImplementedError,
  which names the missing file lock (`fcntl.flock`), before it opens the reads file. No Windows support is
  claimed beyond that, and no Windows run tests it.
- **E7, the MDE at the boundary: the exact gap (2026-09-30; the second review's R4).** Where the gap rounded to
  4 significant digits away from the null would print an effect outside [0, 1], the sentence prints the exact
  gap instead, in the exact form p0 uses (a finite decimal, else "a/b"): "1/3 + 2/3". Everywhere else E2 stands,
  an effect of exactly 0 or 1 included. The exact gap is the MDE's own distance from p0, so the printed effect is
  a probability and still reaches 80% power, and E2's four digits give way there. At p0 = 0.33330001 and n = 2400,
  with an alpha at which only 2400 successes reject (p0 to the 2400th power, say), the MDE is 0.99990703, and the
  sentence now prints "0.33330001 + 0.6666070179300212860107421875", where it printed "+ 0.6667", above 1. This
  closes the limit E2 left at the boundary.
- **E8, an early read reveals nothing about the result (2026-09-30; E3's residual).** An early read's sentence
  carries only the hypothesis name; "read early (read at <the read time, ISO 8601 UTC>; window closed at
  <horizon.end at 12:00 UTC>)"; the prereg id; the data sha256; the number of units used; and the onus version.
  It carries no counts, ties, missing values, p-values, adjusted p, α, family or correction, MDE, test
  description, or warnings, and `assert_quoted` recognises its shape. As built: "faster: read early (read at
  2026-01-08T11:00:00+00:00; window closed at 2026-01-08T12:00:00+00:00); prereg layout@<12 hex>, data sha256
  <12 hex> over 3 units; onus <version>." The read time is the one the read's line records, so render still reads
  no clock, and the data hash is cut to 12 hex digits as in every sentence. E8's list holds no re-read clause, so
  an early re-read's sentence does not name the read it superseded, though its line records `supersedes` and a
  re-read once the window has closed names it: D6's "re-read on different data" is shown only on a read that is
  not early; Amendment 4's E12 reverses this for a re-read on different data, which names it early too. As built after the third review
  (its R3-REG-4): render requires the line's `early` to be the one
  its `at` gives under the rule's horizon (`read_early`, which `record_read` uses to write it), beside D1's
  fields, and refuses a hand-edited flag with PreregError. Before, a flag flipped by hand had render state the
  verdict of a read made before its window closed, or raise a bare AssertionError for a count horizon's read.
- **E9, E1 past single lines: a quote may be hard-wrapped (2026-09-30).** Withdrawn with E1 by Amendment 4's
  E11. When `assert_quoted` looks for quotes,
  a line break together with the indentation and any '>' blockquote markers that open the next line counts as one
  space, so a stale copy wrapped across lines fails and a correct copy wrapped across lines passes. The rendered
  sentence itself stays one line.
  - As built: lines remain E1's unit, except that the lines a rendered sentence, or a copy shaped like one (from
    a verdict to a provenance, found in the whole document read with each break as one space), runs over are
    read as one line; such a quote starts at its hypothesis's name when the name stands just before its
    verdict, so one wrapped between the words of its name is read whole. Reading the whole document as one line
    would have left E1 no unit to hold to the sentence: any document holding the exact sentence would pass, a
    stale copy beside it included. A space left before a break is not part of it, so a copy wrapped that way
    holds two spaces there and fails.
  - As built after the third review: a body's prereg id holds no verdict and no second "; prereg ", so a
    provenance cut short no longer runs on into the lines below it, swallowing a stale copy or the exact
    sentence there (its CL3-1 and R3-REG-1), and finding the bodies takes time linear in the document's length,
    not quadratic (R3-REG-3). And where a read that spans lines is not the sentence, each line it runs over is
    read on its own too, so E1 holds for every line: a stale copy on a line of its own fails even below prose
    whose verdict-like phrase opens a read that runs over it (R3-REG-2).
  - Known limits: another wording not shaped like a rendered sentence, hard-wrapped so that no one line names
    both, still passes; and a stale copy sharing a line with a line of a wrapped exact copy passes, as one
    sharing a line with the exact sentence does.
- **E10, the one-line rule at load (2026-09-30).** `load` refuses a record whose hypothesis names, family names,
  experiment, unit or order_key field names, or file stem contain any character that `str.splitlines` treats as
  a line boundary, so every loadable record renders on one line; render's own one-line refusal stays as a second
  check. This narrows what prereg/1 accepts, before any release. A declared family whose name holds a break, which
  no hypothesis can then name, is refused as declared with no member.
- **Known limits, recorded with these decisions:**
  - A refused read can leave an empty reads file behind when it created the file: `record_read` opens the file
    to lock it before the seal decides, so a `supersedes=` with no earlier read to supersede leaves it there.
  - `read/2` labels hold only "met" and "not met", so the post hoc label (L1 step 4) needs a `read/3` or a
    widening of `read/2` then.

## Amendment 4 (2026-10-05): `assert_quoted` leaves the report step; a re-read says what it differed in

After the third review the maintainer chose between four ways on for `assert_quoted`, and answered the question
E8 left about an early re-read; a review of that build then put two more choices to them. Each choice binds v0.1:

- **E11, `assert_quoted` is split out and rebuilt on explicit quote markers.** `assert_quoted` produced the worst
  finding of each of the three reviews (F3; the second review's C1 and R1; the third's R3-REG-1 and two majors),
  because it guessed where free text quotes a result, and each fix added guessing. It is removed from the
  `report` pull request, with its tests and mutants, so `onus.report` ships `render`, `render_exploratory`,
  `receipt_from_line`, and `MDE_POWER`. It returns in its own pull request, rebuilt so that a document marks each
  quote explicitly and only marked text is checked; that pull request decides the marker's form. E1 and E9 are
  withdrawn with it, and E8's and E10's remarks about what `assert_quoted` recognises or raises no longer
  describe anything built. What stands of E1: the rendered sentence is one line, held by `load` (E10) and by
  render's own refusal.
- **E12, an early re-read on different data names the first read.** An early read that superseded another on
  different data carries "re-read on different data; first read <12 hex>" after its "read early (...)" clause,
  as a read that is not early carries it after its verdict. That a read was a re-read on different data is its
  history, which its reads line already records, and says nothing about the result, so E8's rule that an early
  read reveals nothing about the result stands. As built: "faster: read early (read at
  2026-01-08T11:00:00+00:00; window closed at 2026-01-08T12:00:00+00:00); re-read on different data; first read
  <12 hex>; prereg layout@<12 hex>, data sha256 <12 hex> over 3 units; onus <version>."
  - As built after this amendment's review, on the maintainer's choice of 2026-10-05: the seal requires
    `supersedes` when the labels differ as well as when the data does, so the same data read again under an
    edited record needs it only because a label changed. As first built, that early read carried the clause too,
    and beside an unchanged data hash it told a reader that some verdict differed between the two records. Now
    render sorts a re-read by the reads before it in its file that the seal held it to (those of its experiment,
    or of a record with its file stem): it is one on different data when any of them has another data hash,
    whatever the labels, and otherwise one after a read under a different record. An early read carries the
    clause only for
    the first kind. Whether it does depends on the data hashes alone, since a read on other data needed
    `supersedes` whatever its labels were.
- **E13, a re-read says what it differed in.** A read that is not early and superseded another on the same data
  carries "re-read after a read under a different record; first read <12 hex>" in place of "re-read on different
  data", which its own data hash contradicted there. D6's and E4's wording stands wherever an earlier read of the
  experiment, or of a record with the same file stem, used other data, the first data read again after a re-read
  included.
  - As built after a second review, on the maintainer's choice of wording: the clause speaks of the reads before
    it, not of the first read it names. As first built it said "re-read under a different record", which was
    false of a record edited, read, and put back: the third read is of the first read's own record. The seal and
    render now share one rule for which earlier reads count (`related_reads`), so the two cannot drift apart.
  - As built after a third and a fourth review, on the maintainer's choice: render finds that read, a related
    earlier read under another prereg id, before it says so. Where the lines before a re-read show neither other
    data nor another record, which no reads file written from honest evaluations does (a line was removed, or one
    records labels its data does not give), a read that is not early says only "re-read; first read <12 hex>",
    and an early one carries no clause. It is not refused: a refusal there, as first built, left the honest
    correction of a wrong line unquotable for as long as the line stood in the file.

## Amendment 5 (2026-10-05): `assert_quoted` on explicit quote markers

Amendment 4's E11 left the marker's form to this step. The maintainer chose each point below; each binds v0.1:

- **E14, a quote is marked by hand, and only marked text is checked.** A document marks a quote with the comment
  `<!-- onus:quote -->` before it and `<!-- /onus:quote -->` after it, which Markdown and HTML do not show.
  `assert_quoted(doc, sentences)` takes the document's text and a list or tuple of rendered sentences. Every
  marked span must hold one of the sentences, and every sentence must stand in at least one span; otherwise it
  raises AssertionError, naming the span's line or the sentence that is missing. Nothing is parsed: not a sentence, and not a marker beyond its exact
  text, so `render`'s and `render_exploratory`'s sentences are checked alike, and a stale copy inside markers
  fails whatever record or read it came from, because it is none of the sentences.
  - The marker carries no key. A record id and hypothesis name in the marker were considered and set aside:
    they would be a second copy that can go stale, would need parsing where ids and names may hold spaces, and
    would hide a span keyed to an older record from a check of the newer one.
  - **Whitespace only.** A span is compared with a sentence after the ends of each are stripped and every run of
    whitespace in each, as `str.split` reads it, is read as one space. So a quote may be hard-wrapped or
    indented. Nothing else may differ: a `>` opening a wrapped line inside a blockquote fails.
  - **A marker must be exact.** The ten characters "onus:quote" may stand in the document, in any case, only
    inside one of the two markers. A marker with other spacing round them, in capitals, with anything added, or
    left unfinished raises AssertionError, where it would otherwise mark nothing and leave its quote unchecked. So
    does a closing marker with no opening one, an opening marker inside a span, and a span never closed.
  - It raises TypeError for a document that is not a string and for sentences that are not a list or tuple of
    strings, a single string included; and ValueError for no sentences, and for a sentence that is empty, only
    whitespace, or holds "onus:quote", which could stand in no span.
  - Known limits, after this step's review: a copy of a result outside any markers is not found. A slip inside
    the ten characters ("onus: quote", "onus-quote") is not caught: such a pair marks nothing, so a stale copy
    between it passes when the sentence is also marked exactly elsewhere, and when it is not, the check fails
    for the sentence, naming no line. Catching more would mean guessing which comments were meant as markers.
    Prose that names the marker, or shows it as an example, fails the check. The document is read as plain
    text, so a marker pair inside a code block or a longer comment marks a quote too. And a sentence that
    differs from another only in its whitespace is the same sentence to this check.

## Amendment 6 (2026-10-07): step 4's first choices, and who may push

Before any of step 4 was written, the maintainer chose each point below from options; each binds v0.1. E16 was
built with this amendment, E17 with `baseline` after it, and E18 with `signoff`, where E19 to E21 were chosen.

- **E15, a session may push its branch and open its pull request.** Once `make check` is green on the head
  commit, one targeted adversarial review has run and its findings are fixed or listed, and the leak scan with
  its positive control is clean, a session pushes the branch and opens the pull request without asking. Merging
  and tagging still need the maintainer's word, per item. This replaces the rule that every push and pull
  request needed that word.
- **E16, a scrubbed value becomes a token numbered by the value.** `iso_dates`, `iso_timestamps`, `uuids`,
  `hex_ids`, and `pattern` write "<date-1>", "<hex-2>": within one text, values are numbered from 1 in the order
  they first appear, and equal values share a number, so a baseline still shows which ids were equal and fails
  when two are swapped or merged. The cost is that a new id early in an output renumbers the later ones in the
  diff. A flat token and a per-scrubber switch were the options set aside. `paths` writes the name its caller
  gave, unnumbered.
  - As built, chosen in the build and open to veto:
    - A scrubber is a `Scrubber`, a frozen, callable, named function from a text to a text, so that `baseline`
      can record which scrubbers shaped an output; `chain` takes only these, and `redactor(fn)` is how a plain
      function gets a name (its module and qualified name).
    - Only a real value is replaced: "2026-13-45" and "2026-01-08T25:00" stay, as does anything that runs on
      into a letter or digit on either side. The date inside a timestamp is left to `iso_timestamps`, so the
      two may be chained in either order.
    - `hex_ids(*lengths)` takes the exact lengths to replace, each at least 8, with no default, and never
      replaces a run of digits alone, so no scrubber shipped here can replace a number. The cost: an id that
      happens to hold none of the letters a to f stays, and its comparison fails, visibly; that is about 36 in
      10,000 ids of 12 digits and under 1 in a hundred million of 40. For a short id, `pattern` names what
      stands round it.
    - `paths` also replaces the other spelling of a path under `/var`, `/tmp`, or `/etc`, with or without
      `/private`; the plan named only `/var`. It replaces a path only where it stands whole ("/srv/app2" is not
      "/srv/app"), and tries the longest mapped path first.
    - A token's name is a lower-case letter followed by lower-case letters, digits, or underscores.
  - Known limits: a text that already holds something shaped like a token ("<date-1>") is not told apart from a
    scrubbed one; a timestamp is numbered by how it is written, so one moment written in two zones is two
    values; and `pattern` can be handed a regex that matches numbers, which nothing here can refuse.
- **E17, `baseline` runs the producer itself and records it beside the approved file.** The call is
  `assertApproved(producer, *args, scrubbers=(), label="", ext=".md", **kwargs)`: the helper calls
  `producer(*args, **kwargs)`, scrubs the result, and compares. It records the producer's module and qualified
  name, a sha256 of the canonical JSON of the arguments, and the scrubbers' names in
  `<name>.approved.meta.json` beside the approved file, so the recorded producer is what made the output and
  the approved file stays the scrubbed output byte for byte. The arguments must be JSON-serializable. This
  replaces `assertApproved(received, *, label="", ext=".md")`, which could learn none of the three. Set aside:
  the caller naming the producer of a text it passes in, where the record would be a claim; and a header inside
  the approved file, where a JSON baseline would stop being JSON.
  - As built, chosen in the build and open to veto:
    - **What "real" means.** A producer is real when importing its recorded name gives it back, it is callable
      and no mock, and its source file lies outside the folder that holds the approved folder (the tests). So a
      bound method, a lambda, a `functools.partial`, a built-in, and a function written among the tests are
      refused. `assertApproved` checks this before it runs the producer, and `ApprovedProducersAreReal`, mixed
      into a test case with `approved_dir` set, checks every record on disk, and that each approved file has
      one record and each record one file.
    - **Where files go.** The approved folder is `approved` beside the test's own file, unless the class sets
      `approved_dir`. A mismatch writes the received text to
      `<temporary folder>/onus-received/<8 hex of the approved folder's path>/`, where the plan said
      `<repo-sha8>`: the helper never asks git which repository it is in.
    - **Recording.** Under `ONUS_APPROVE_ROOT` the root must be an absolute path with a `.git` entry and must
      hold the approved file; an empty or relative value is refused, not read as the current folder. `forbid=`
      regexes read the scrubbed output. A file already equal to the output is not rewritten. A record that no
      longer matches the call fails the test even when the output matches.
    - **onus has no `make approve` of its own**, because it has no tier-1 files: its tests of `baseline` build a
      scratch checkout. An adopter's target is one line, setting `ONUS_APPROVE_ROOT` to
      `git rev-parse --show-toplevel` for one run of its suite.
  - Known limits: the producer's own keyword arguments cannot be named `scrubbers`, `label`, `ext`, or
    `forbid`; a test and label have one record, so two `ext` values under one label collide; JSON reads the
    keys 1 and "1" of an argument as one; and whether `onus`'s own outputs (a rendered sentence, say) should be
    held to tier-1 files here is undecided.
- **E18, the environment `signoff record` refuses under.** It refuses when a variable named `CLAUDECODE`,
  `AI_AGENT`, `CI`, or `GITHUB_ACTIONS` is set, or any whose name starts with `CLAUDE_CODE_`, `CODEX_`,
  `CURSOR_`, `AIDER_`, `GEMINI_CLI`, or `COPILOT_`, and names the variable it tripped on. It does not refuse on
  `ANTHROPIC_*` or a bare `CLAUDE_*`, which a person's own shell profile may set. Exact names only, which go
  stale, and every name that looks related, which could refuse the maintainer at their own terminal, were set
  aside. It is a tripwire, as before; the control is step H.
- **E19, a revocation is a line that names the sign-off it revokes (2026-10-08).** `revoke` appends a
  `signoff/1` line for the artifact with `sha256` and `bytes` null, nothing bound, and `supersedes` set to the
  hash of the sign-off line it revokes; the person types the first eight hex digits of that line's hash.
  `check_signoff` answers REVOKED while it is the artifact's newest line, and a later `record` signs the
  artifact again. A second schema for revocations, and no revocation in v0.1, were set aside.
- **E20, `bound` is `{path: sha256}`, and it is checked (2026-10-08).** `record --bind <file>` stores each
  file's path from the ledger's folder, never outside it, with its sha256, and `check_signoff` answers CHANGED,
  naming the file, when one no longer matches. Recording without checking, and a free-text note, were set aside.
- **E21, `reviewed_by` is a required argument (2026-10-08).** `--reviewed-by <name>`, with no default, shown
  back at the terminal before the digits are typed. It is one line and holds no "@", so no address is written
  into a ledger. It is never read from git or the login.
  - As built, for E18 to E21, chosen in the build and open to veto:
    - **`supersedes` is always the newest earlier line for the artifact**, or null for its first: a re-signing
      names the sign-off or revocation before it, and `record` fills it in. A ledger where a line names any
      other is CORRUPT, as is a revocation of what is not a sign-off.
    - **Fail closed means the whole ledger.** One malformed line, one break in `prev`, a file not ending in a
      newline, or bytes that are not UTF-8 make every artifact CORRUPT, one the ledger never names included.
      No ledger at all, or an empty one, is UNSIGNED.
    - **The signed content is kept** in `<ledger>.blobs/<sha256>`, mode 0444, so CHANGED can show a diff. A
      kept copy that no longer hashes to its name is CORRUPT; one that is gone leaves CHANGED without a diff.
    - **The terminal is `/dev/tty`, opened by descriptor,** and must be a terminal: a file or pipe in its
      place is refused, and standard input is never read. What is typed must be exactly the first eight hex
      digits, lower case. The same content with the same files bound is not signed twice.
    - **The command line** is `python -m onus.signoff record|revoke|check`. `check` exits 0 only for SIGNED
      (10 UNSIGNED, 11 CHANGED, 12 REVOKED, 13 CORRUPT), and a refusal exits 20.
    - `record` and `revoke` need `fcntl`, imported when they run, as `record_read` does (Amendment 3, E6).
  - Known limits: a refused first sign-off leaves an empty ledger file behind; the bound files' contents are
    not kept, so a changed one is named without a diff; the library's own tests reach `record` by pointing it
    at a pseudo-terminal and clearing the environment, which any process could do, so these checks stay
    tripwires and step H stays the control; and nothing here binds a prereg amendment yet, which arrives with
    the prereg work.

## The library

### Shape

- **Layout:** a flat package `onus/` at the repository root, with `py.typed`. A `src/` layout under
  `pip install -e` makes every mutant survive under mutt_check, so the package stays flat.
- **Subpackages, named by intent:** `onus.stats`, `onus.prereg`, `onus.report`, `onus.baseline` (tier 1),
  `onus.signoff` (tier 2), `onus.scrub`, and `onus.invariants` (the Hypothesis part; not `property`, which
  would shadow the builtin). `prereg` will import `signoff` (L1 step 4), since amendments are bound by
  sign-offs. Built so far: `stats`, `prereg`, `report`, `scrub`, `baseline`, and `signoff`.
- **Python:** `requires-python >=3.11`, with CI covering 3.11 to 3.14. Locally, `.python-version` pins the
  exact patch and the floor check (it compiles the package) runs on an exact 3.11 patch, both from pyenv and
  handed to uv by path; in CI each matrix job supplies its own interpreter.
- **Dependencies:** `dependencies = []`. The only extra is `invariants = ["hypothesis>=6.168.1,<7"]`, and only
  `onus.invariants` imports it. (Hypothesis 6.168.1 needs Python 3.10 or later.)
- **Tooling:** black and ruff at 120 columns with the D, ANN, B, UP, and I rules and Google docstrings; strict
  mypy; coverage with `branch = true` and `fail_under = 95`. `tools/` is inside lint, type, and coverage scope.
- **Packaging and release** follow mutt_check: setuptools 77 or later, a dynamic `__version__`, SPDX MIT, a
  tag-triggered release workflow, and rulesets that make `main` pull-request-only and `v*` tags permanent.
- **Gate:** `make check` is the whole gate (see `AGENTS.md`). The opt-in targets `reference` and `sims` (and `calibrate`,
  from v0.2) are never part of it.
- **Test fixtures are synthetic only.** No client names, machine paths, or real addresses.

### stats: stdlib only, exact rationals

- Exact tails are computed in `fractions.Fraction`, and results are frozen dataclasses carrying `p_exact`,
  `p_value`, counts, ties, missing, method, and warnings.
- `decide(result, alpha="0.05")` rejects iff `p_exact <= Fraction(alpha)`.
- **`alternative` and `method` are keyword-only, with no default.**
- **v0.1:**
  - `binomial`: `binom_tail`; `binomial_test` (two-sided only at p = 1/2); `sign_test(wins, losses, *, ties,
    alternative, method)`; `paired_sign_test(first, second, *, alternative, missing, method)`, where `missing` is `"refuse"` or `"drop"`;
    `mcnemar_exact`.
  - `intervals`: `wilson(k, n, *, confidence=None, z=None)` (0.95 unless `z` is given) and `clopper_pearson`, both raising
    `EmptySampleError` at n = 0.
  - `multiplicity`: `holm`, `benjamini_hochberg`, and `Family`, which refuses undeclared members and incomplete
    adjustment.
  - `power` (exact DP): `sign_test_power`, `sign_test_mde`, `binomial_power`, `binomial_mde`, and
    `sequential_size`.
- **v0.2 (step L2):**
  - `ranks.mann_whitney(..., method="exact"|"normal")`: exact is the tie-conditional permutation null; normal
    has tie and continuity corrections.
  - `cluster.cluster_bootstrap`, reporting valid draws, raising `InsufficientDraws` below b/2, and warning under
    20 clusters; and `cluster.cluster_sign_flip_test`.
  - `binomial.rate_ratio_test`.
- **Freeze rule:** a released function's numeric output never changes; a fix is a new `method=` value.
  Known-wrong legacy behaviour is never reproduced in the library.
- **Out of scope:** a Bayesian layer, automatic test choice, post hoc power, sequential-until-significant
  helpers, numpy or scipy at runtime, and a pytest plugin.

### prereg and report

- **`prereg_id(path)`** returns `"<stem>@<first 12 hex digits of the file's sha256>"`. Any edit gives a record
  a new id.
- **Records** use `"prereg/1"` JSON and reject unknown keys. Fields: experiment, registered, hypotheses
  `[{name, test, alternative, method, alpha, family}]`, families, unit, cluster_key, order_key, horizon
  (`{kind: "count", n}` or `{kind: "days", days, start}`), looks, `bound_artifacts {path: sha256}`, and
  provenance. `load` also requires `p0` on a `binomial_test`, where two-sided is allowed only at p0 = 1/2, and
  refuses it on a `sign_test`; takes `families` as `{name: {correction}}`; takes `alpha` and `p0` as exact
  numbers written as strings, such as `"0.05"`; and requires `bound_artifacts` paths that stay inside the
  record's folder. These are as built, not among the five defaults Amendment 1 ratifies. Since Amendment 3's E10,
  `load` also refuses a hypothesis name, family, experiment, unit or order_key field, or file stem holding a line
  break.
- **Amendments** are separate `<stem>.amend-YYYY-MM-DD.json` files, each bound by a tier-2 sign-off (L1 step 4).
- **Evaluation and read-recording are split**, because a name must not hide a write:
  - `evaluate(rule, data, *, as_of=None)` is pure. It refuses before the horizon. A count horizon uses exactly
    the first N units in `order_key` order; a days horizon needs `as_of` past its window and uses the units
    dated inside it.
  - `record_read(rule, evaluation, *, reads_path, supersedes=None, reason=None)` appends a `read/2` line to a
    reads file and returns a `ReadReceipt`. The read time is the clock's (D8), and the seal and its override
    are D6's.
  - `report.render` requires a receipt, so displaying a verdict records it. Its signature and checks are
    Amendment 2's D1, D5, and D6; exploratory results use `render_exploratory` (D4).
- **Post hoc:** an amendment signed after the first read of a hypothesis it touches labels that hypothesis
  post hoc. The labels are met / not met / pending today, and render shows "read early" in place of a verdict
  (D5); post hoc arrives with L1 step 4, and needs a `read/3` or a widened `read/2` (Amendment 3).
- **render's sentence** is one line: load refuses a record whose names would break it, and render refuses such
  a sentence too (Amendment 3, E1 and E10). It carries n, discordant pairs and ties, sidedness, the family
  correction, **the MDE whenever a read that is not early is not met** (D2, D3; Amendment 3, E2, E3, and E7), the
  prereg id, a data hash, and the library version. An early read's sentence carries only the name, when it was
  read and when its window closed, and that provenance (E8). A re-read on different data, early or not, names
  the first read, and one of the same data after a read under a different record does once it is not early
  (D6; Amendment 4, E12 and E13). It reads no wall clock.
- **`report.assert_quoted(doc, sentences)`** fails a test unless the quotes a document marks, between
  `<!-- onus:quote -->` and `<!-- /onus:quote -->`, are exactly the rendered sentences: every marked span holds
  one of them, whitespace aside, and each stands in at least one span (Amendment 5, E14). Only marked text is
  checked.

### baseline, signoff, and scrub (approval testing)

- **`scrub`:** `chain`, `iso_dates`, `iso_timestamps`, `paths(mapping)` (including `/private/var` and `/var`),
  `uuids` and `hex_ids(*lengths)`, `pattern(regex, name)`, and `redactor(fn)`, each a named `Scrubber`. A value
  becomes a token numbered by the value (Amendment 6, E16). No PII rules ship, and numeric scrubbers on stats
  output are forbidden: none ships, and `hex_ids` never replaces digits alone.
- **Tier 1 (`baseline`):**
  - Tests use `ApprovedMixin.assertApproved(producer, *args, scrubbers=(), label="", ext=".md", **kwargs)`
    (Amendment 6, E17). Approved files are
    `tests/approved/<module>.<Class>.<method>[.<label>].approved<ext>`, committed.
  - On a mismatch the test fails with a diff and writes the received file under
    `$TMPDIR/onus-received/<repo-sha8>/`. A missing approved file fails; it never skips.
  - **Recording** happens only under `make approve`, which sets `ONUS_APPROVE_ROOT` to the invoking checkout's
    top level. The helper refuses unless the approved path resolves under that root and the root is a git work
    tree, so a mutation sandbox refuses.
  - `forbid=` patterns apply while recording. Each approved file's sidecar carries the producer,
    `inputs_sha256`, and the scrubbers, never a timestamp (E17). `ApprovedProducersAreReal` refuses test-local or mock producers.
- **Tier 2 (`signoff`):**
  - **Ledger:** the adopter passes the ledger path. Lines are `{"schema": "signoff/1", artifact, sha256, bytes,
    bound, supersedes, reviewed_by, at, tool, prev}`, hash-chained. Blobs are content-addressed, mode 0444.
  - **Ids** are exact, matching `^[a-z0-9][a-z0-9._-]*:[A-Za-z0-9._/-]+$`; no globs.
  - `check_signoff` returns SIGNED, UNSIGNED, CHANGED (with a diff), REVOKED, or CORRUPT, and **fails closed** on
    a malformed line or a broken chain.
  - **`record`** refuses when any agent-session environment variable is set (Amendment 6, E18, lists them) or
    `/dev/tty` cannot be opened, shows the diff, reads a typed 8-hex prefix from `/dev/tty`, then appends under
    flock and fsync.
  - **These are tripwires; the control is step H.**

### invariants (the `invariants` extra)

- **Profiles:** `use_profile()` defaults to "gate" (`derandomize=True`, `database=None`, `deadline=None`,
  `max_examples` 200 in the library and 50 in adopters; health-check failures fail). "explore" loads only under
  `ONUS_HYPOTHESIS_PROFILE=explore`, with its database under `~/.local/state/onus/explore/<repo>`.
- **Storage:** `HYPOTHESIS_STORAGE_DIRECTORY` points outside the worktree, and `.hypothesis/` is gitignored
  anyway.
- **Strategies** are independent grammars only (`emails`, `in_context`, `markdown_text`,
  `normalization_variants`). Adopters own the oracles and the bounds.
- **`python -m onus.invariants examples <log>`** prints `@example` lines for a person to paste. It never edits
  source.

### How we know the library is right

1. **Brute-force oracles** in `make check`: all 2^n outcomes for n ≤ 14 (built); all labelings with ties for
   n + m ≤ 12 and all 2^C sign flips arrive with the v0.2 tests they check. Two coverage tests: exact size ≤ α for n ≤ 200 and α in
   {0.01, 0.05, 0.10}; and Clopper-Pearson coverage at least nominal on a 1001-point grid.
2. **The reference fixture:** `make reference` recomputes answers with pinned scipy and statsmodels versions
   and commits them with the script's sha256; a drift test guards it.
3. **Hypothesis properties:** tail complement; two-sided = min(1, 2 × the smaller tail); sign-test symmetry and
   monotonicity; U sums, and U(x, y) + U(y, x) = nm; interval containment and reflection;
   Bonferroni ⊆ Holm ⊆ BH; power monotone in the effect and in α (never in n); and `sequential_size` with one
   look equals the fixed size.
4. **Simulation cross-check:** `tools/sims/ht_sims.py`, with its output committed; a test asserts that the exact
   DP matches within 3 standard errors.
5. **Mutants** in `mutt_check.toml`, each with the test that kills it:
   - **Tails and tests:** tail off by one; sidedness flipped; two-sided not doubled; cap removed; `<=` to `<`
     (killed at α = 1/16 with 4 to 0); continuity correction dropped; tie variance dropped.
   - **Intervals:** wilson z hardcoded; n = 0 returns a zero interval.
   - **Families and power:** Holm running maximum removed; incomplete family allowed; undeclared member
     accepted; MDE uses the observed effect.
   - **Missing data and defaults:** `missing="refuse"` silently drops; `alternative` gains a default; `method`
     gains a default.
   - **Bootstrap:** invalid draws dropped silently; percentile off by one.
   - **Pre-registration:** horizon not enforced; `evaluate` uses more than the first N or ignores `order_key`;
     unknown prereg key accepted; amendment after a read accepted; `render` without a receipt.
   - **Tier 1:** approved file overwritten automatically; missing approved file created or skipped; received
     file written into the worktree; `make approve` records outside the root; `forbid` ignored while recording.
   - **Tier 2:** record allowed under a session; tty replaced by stdin; glob id accepted; corrupt line skipped;
     broken `prev` chain accepted.

   `mutt_check.noop.toml` must **survive**. Mutated files are restored from a pre-mutation snapshot, never with
   `git checkout <path>`.

## Order of work

**Rules for every step:**

- A branch per session, then a pull request; files staged by path. `make check`'s raw output, with its test
  count, goes in the pull request body.
- **The maintainer's explicit word, per item,** is needed to merge or tag. A session pushes its branch and opens
  its pull request without it, once the gate is green, one targeted review has run, and the leak scan is clean
  (Amendment 6, E15).
- **Before each push,** scan the tree, the commit messages, and the pull request body for names of people,
  companies, customers, and private repositories, machine paths, and email addresses, with a positive control.
- Deliberate corner-cuts are marked in place: `# ⚠ SHORTCUT (date) — what — ceiling — exit`.
- Every session ends with a note in `docs/handoffs/`.

**L1. Library v0.1.0:**

1. The scaffold, green on an empty package (PR #1, merged).
2. `binomial`, `intervals`, `multiplicity`, and `power`, with the oracles, the reference fixture, and the sims
   cross-check (PR #3, merged). **Open, no owner yet:** the plan also named parity scripts here, comparing
   the library with the adopters' earlier hand-written tests; they were not built, and no later step owns them.
3. `prereg` (PR #5, merged), then `report` to Amendments 2, 3, and 4 (PR #8, merged), then
   `report.assert_quoted` on explicit quote markers, as its own pull request (Amendment 5).
4. `scrub`, `baseline`, and `signoff` (built, to Amendment 6's E16 to E21), each its own pull request, plus the
   prereg work PR #5 deferred: amendment files and their sign-off
   binding, the post hoc label in `prereg` and `render` (with the `read/3` or widened `read/2` it needs,
   Amendment 3), the "amendment after a read accepted" mutant, and Amendment 1's open count-horizon decision.
5. `invariants`.
6. The v0.1 mutants: each part brings its own, and the no-op spec (`mutt_check.noop.toml`) is already enforced,
   so this step checks that the whole list below is present and caught.

Then the leak scan, the push, and the pull request; and the merge and the `v0.1.0` tag, each on the maintainer's word.

**Verify:** every mutant caught, the no-op survives, `make reference` reproduces the fixture byte for byte, and
`git status --porcelain` is empty after two runs.

**H. Tier-2 control (right after L1; proposed, applied by the maintainer).** The library's `record` checks
are tripwires, not a control. H is a control outside the library that keeps agent sessions from making a
sign-off, with test cases for what it must and must not block, and a log of what it blocks. The maintainer
applies it before the first tier-2 sign-off is relied on.

**L2. Library v0.2.0 (after the first adopter integrates v0.1):** `ranks`, `cluster`, and `rate_ratio_test`,
with their oracles and mutants, and `make calibrate`.

## Maintainer-only items

- Every merge and tag (pushes and pull requests were theirs too until Amendment 6, E15).
- Installing the pinned interpreter patches.
- Each tier-2 `signoff record`, from their own terminal.
- Applying step H before the first tier-2 sign-off is relied on.
- Declaring an adopter's confirmatory families.

## Defaults chosen here (vetoable)

- **Floor and arithmetic:** floor 3.11; exact rationals; reject iff p ≤ α.
- **Test definitions:** two-sided binomial only at p = 1/2; n = 0 raises.
- **Structure:** evaluate and record_read are split, and render requires a receipt; the v0.1 / v0.2 split.
- **Operations:** adopter `max_examples = 50`, pending a timing measurement in an adopter; received files in
  `$TMPDIR`.

## Risks

- **A tier-2 ledger is only as durable as its adopter keeps it**; the library keeps no copy, and until H lands
  only the tripwires stand between an agent session and a ledger.
- **Bit-identical bootstrap intervals** depend on CPython's `random.choice` stream. An RNG canary must fail
  loudly on drift.
- **Exact DPs** need a measured time budget.
- **MDE lines will show most comparisons are underpowered.** The amendment ledger makes any after-the-fact
  loosening visible.

## Verification (end to end)

1. **Library:** every mutant caught; the no-op survives; the reference fixture reproduces byte for byte; the
   worktree is clean after two runs; the leak scan is clean before each push.
2. **Tier 2:** from an agent session, `signoff record` refuses, and once H is applied, H blocks it too. From
   the maintainer's terminal, the record, status, and diff round trip works. A hand-corrupted line and a broken `prev` chain both return CORRUPT.
