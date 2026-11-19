# Gold Set Annotation Guide — Agent 4 Event Types

You are labelling about 97 news articles by hand. These labels are the **ground truth** used to measure the
risk models, so accuracy matters more than speed. Plan on about 20–30 seconds per article.

---

## 1. The file

Open `data/risk/gold_to_label.csv` in Excel or Google Sheets.

| Column | What to do |
|---|---|
| `id` | Don't edit |
| `title`, `body` | Read these |
| `gold_in_scope` | Fill in `true` or `false` |
| `gold_event_type` | Fill in **one** of the 8 event types below, or leave it blank if out of scope |
| `notes` | Optional: write why, if you were unsure |
| `annotator` | Add this column and fill in your initials |

> **Do not open `gold_key.csv`.** It contains the LLM's answers and will bias you.
> **Label on your own.** Don't discuss articles until everyone has finished the shared rows.

---

## 2. Step 1 — Is it in scope?

`gold_in_scope = true` if the article is mainly about **sport** (any sport, any level) or **films, OTT
series and film celebrities**.

`gold_in_scope = false` for everything else, such as music-only, TV news, politics, business or tech, even if
a sports star or actor is mentioned in passing.

If it's out of scope, leave `gold_event_type` blank and move on.

---

## 3. Step 2 — Pick the event type

Ask yourself: **what actually happened in this story?** Label the event itself, not the article's tone.

| Event type | Choose it when | Examples |
|---|---|---|
| `routine` | Nothing has gone wrong: results, previews, transfers, signings, releases, trailers, box office, awards, reviews, interviews | "Kohli scores century", "Film crosses ₹100 cr", "Club signs striker" |
| `controversy` | Criticism, feuds, offensive remarks, fan backlash, boycott calls or scandals, **with no legal action or official sanction yet** | "Coach slams referee", "Actor's remark sparks backlash" |
| `injury` | Injury, illness or health scare of a player, actor or crew member, including being ruled out or sidelined | "Star ruled out for 6 weeks with hamstring tear" |
| `legal` | Lawsuits, arrests, criminal charges, police investigations, court hearings or rulings | "Player arrested for drunk driving", "Studio sued over copyright" |
| `ban_suspension` | A ban, suspension, fine or sanction by a league, governing body, studio, censor board or government, **not** for doping or fixing | "NBA suspends player one game", "Censor board bans film" |
| `cancellation` | A match, tournament, event, shoot or release cancelled, postponed, called off, abandoned or relocated | "Match abandoned due to rain", "Release pushed to next year" |
| `integrity` | Doping, failed drug tests, anti-doping cases, match-fixing, spot-fixing, illegal betting, bribery or corruption in sport, **including any ban that results** | "Sprinter tests positive", "Player banned 4 years for doping" |
| `death_tragedy` | Death, fatal accident, stampede, violence, attack or disaster involving people in the story | "Former champion dies at 83", "Stampede at stadium" |

### If more than one applies

Pick the **most serious** one, using this order:

`death_tragedy` > `integrity` > `cancellation` > `ban_suspension` > `legal` > `injury` > `controversy` > `routine`

For example, "player arrested after a crash that killed a pedestrian" is `death_tragedy`.

---

## 4. Tricky cases (agreed rules)

| Situation | Label |
|---|---|
| Failed drug test, doping charge or doping ban | `integrity` (never `controversy`, `legal` or `ban_suspension`) |
| Someone **denies** doping or fixing allegations | `integrity` |
| Ban or suspension for anything other than doping or fixing (fighting, conduct, red card) | `ban_suspension` |
| Fine by a league | `ban_suspension` |
| Arrest, court case or police probe with no league sanction | `legal` |
| Contract dispute in talks or arbitration, not in court | `controversy` |
| Labour talks or strike **threat** | `controversy`; if games are actually called off → `cancellation` |
| Tributes, obituaries, "celebrities mourn X" | `death_tragedy` |
| Anniversary or retrospective of an old death | `routine` |
| Film or episode **review** whose plot involves death or crime | `routine` (rule: reviews are always routine) |
| A player **returns** from injury | `routine` |
| Released from prison, case dropped, acquitted | `legal` |
| Player misses a game for personal or family reasons | `routine` |
| Squad news listing several injured players | `injury` |
| Opinion piece or debate (for example "should athletes be paid?") | `routine`, unless it is about a specific incident |
| Headline is clickbait but the body is routine | Label what the **body** says happened |
| You genuinely can't decide | Pick your best guess and write `unsure: X or Y` in `notes` |

---

## 5. Workflow for multiple annotators

1. **Shared rows (first 25 rows):** **everyone** labels rows 1–25, each in their own copy of the file, named
   `gold_<initials>.csv`.
2. **Compare:** send the copies to be merged. Agreement is calculated, and every disagreement is listed.
3. **Resolve:** discuss the disagreements, agree on a final label, and add any new rule to section 4 above.
4. **Split the rest:** divide rows 26–97 between annotators. Each person labels only their own rows.
5. **Merge:** combine everything into one final `gold_to_label.csv`, with one label per row.

**Target agreement on the shared rows: 80% or higher.** If it's lower, the definitions are being read
differently. Resolve that before splitting the rest.

---

## 6. Quick checklist before you hand in

- [ ] Every row has `gold_in_scope` filled in (`true` or `false`)
- [ ] Every in-scope row has exactly one `gold_event_type`, spelled exactly as in the table
- [ ] Out-of-scope rows have a blank `gold_event_type`
- [ ] Unsure rows have a note
- [ ] Your initials are in the `annotator` column
- [ ] You did not open `gold_key.csv`
