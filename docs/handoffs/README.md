# Handoff notes

One note per working session, written before the session ends, so the next session (or a person) can pick up
the work without the conversation it came from. They are kept, not deleted: in date order they are the
project's progress log.

## Naming and shape

- File: `YYYY-MM-DD-<short-topic>.md`, dated the day the session ends. A second note on the same day takes a
  different topic.
- Each note opens with this front matter, so the notes can be indexed outside the repository:

  ```yaml
  ---
  date: 2026-09-25
  scope: what the session worked on
  state: done | in-progress | blocked
  prs: [1]
  next: the first action the next session should take
  ---
  ```

- Then, in this order: **State** (what is true now, verified, with shas and PR numbers), **Done this session**,
  **Open** (known defects and undecided questions), **Next actions**, in order.
- A note describes its moment and is not edited afterwards; a later note corrects an earlier one.

## Rules

- The repository is public: no home paths, email addresses, or names of people, companies, customers, or
  private repositories. Scan the note with the rest of the diff before committing.
- A note says what was verified and how (the raw `make check` result belongs in the PR, not here).
- `2026-09-24-scaffold-review-rounds-1-4.md` predates this convention and is kept as it was written, so it
  has no front matter, and its instruction to delete it once PR #1 merged no longer applies.
