# News-value codebook v1 (research2)

You see a news item's **headline** and **abstract** (abstracts longer than 600 characters are cut and end in "…"). Rate the item on **seven news values**, each from **1 to 5**.

## Scale

- 1 = not present
- 2 = weak or marginal
- 3 = clearly present, moderate
- 4 = strong
- 5 = very strong, central to the item

## The seven values

The definitions in this table are the same ones the LLM is given, word for word. The examples are invented and do not come from MIND.

| Value | Definition | 1 looks like | 3 looks like | 5 looks like |
|---|---|---|---|---|
| **conflict** | conflict, negativity or bad news (disputes, violence, crime, disasters, deaths, losses, scandals, failures) | a pumpkin-bread recipe | council members argue over a budget; a company misses its earnings target | a mass shooting, a deadly hurricane, a war |
| **magnitude** | scale of impact (how many people are affected, or how large the event, sum or consequence is) | one family renovates its kitchen | a state-wide rule change; a company cuts 500 jobs | a national election result; a disaster affecting millions; a deal worth billions |
| **prominence** | involvement of famous people, celebrities, powerful organisations, governments or nations | ordinary private people, no notable names | a local mayor, a mid-size company, an athlete known to fans | the US president, Apple, Taylor Swift, the UN |
| **surprise** | how unexpected, unusual or out of the ordinary the content is | a routine forecast or a regular-season game | an unusual twist in an ordinary story | a bizarre, shocking or first-ever event |
| **utility** | practical use to the reader (information they could act on: health, money, safety, weather, travel, shopping, how-to) | celebrity gossip; nothing to act on | general tips; background a reader might use | a product recall, a storm warning with instructions, how to claim a refund |
| **entertainment** | entertainment or human interest (showbiz, sport as spectacle, humour, animals, quirky or emotional personal stories) | a dry policy or finance report | a sports match report; a light feature | celebrity drama, a viral animal video, a heart-warming personal story |
| **importance** | public importance (how much a well-informed citizen ought to know this, however entertaining or dull it is) | trivia, gossip, a listicle | civic information of moderate consequence | major public affairs: an election, a war, a public-health crisis, major legislation |

## Rules

1. **Judge only from the text you are shown.** Don't look the article up, and don't guess how many people read it.
2. **Rate each value on its own.** The values don't exclude each other: a story can be both important and entertaining, or neither.
3. **Ordinary sports wins and losses** get conflict 1 or 2, unless there is violence, scandal or serious injury.
4. **Weather forecasts:** utility is usually high. Importance depends on how severe the weather is.
5. **Clickbait and listicles:** rate what the text actually says, not what it hints at.
6. If the abstract is "(none)" or says nothing useful, **rate from the headline**.
7. **Use the whole 1–5 range.** Don't fall back on 3 when you're unsure; pick your best estimate.
8. **Work independently.** Don't discuss items with the other labeller until both files are handed back.

## Practicalities

- 100 items. About 45–60 seconds each, so roughly 1.5 hours. Take a break halfway.
- The **done** column shows ✓ once all seven scores in a row are filled.
- **notes** is optional. Use it for items you found genuinely ambiguous.
