# research2 — literature check (step 5)

**Date:** 2026-11-15. **Read in full:** the four PDFs in this folder. **Not read:** works cited only through those papers (listed in §2). Read those before citing them for anything beyond "exists".

## 1. The four papers in this folder

| Paper | What it does | Overlap with us |
|---|---|---|
| **Sotic & Kamps, "What Makes a User Click on a News Item? Understanding News Values of Visual Content in News Recommendation"**, TPDL 2025, LNCS 16097, pp. 321–339 (`978-3-032-05409-8_19.pdf`) | Scrapes 15,080 MIND lead images. Three coders label 1,054 images for 11 visual news values (Caple & Bednarek typology plus Joy and Sorrow); κ is mostly above 0.70, Consonance 0.26–0.32. GPT-4.1 detects the values: image-only macro-F1 0.430, fusion 0.420, text-tags-only 0.287. Images were sampled across low, medium and high click-rate strata. | **Closest work.** Same dataset, same theory, LLM annotation. But it covers **images, not headline or abstract text**, and it **does not test news values against clicks**. It calls that future work ("…to model or assess the extent to which visual NV factors help explain engagement outcomes such as click-through rates"). It has no within-impression design and no importance-vs-engagement analysis. |
| **Meese & Herbertson, "Civic Ground Truth in News Recommenders: A Method for Public Value Scoring"**, NORMalize workshop @ RecSys 2025 (`2510.22865v1.pdf`) | Proposes getting public-value labels from a nationally representative Australian survey (News.com.au, one month), then extending them to the whole corpus via headline news-value features adapted from Piotrkowicz et al. (prominence from Wikipedia views, sentiment, surprise, clickbait features) plus k-means. **A method proposal with no results.** | Supports our "importance" dimension as a normative signal distinct from engagement. Their importance labels come from people, ours from an LLM validated against people; they don't use MIND or clicks. We cite it as motivation. |
| **Vrijenhoek, "Do you MIND? Reflections on the MIND dataset for research on diversity in news recommendations"**, BIAS 2023, Springer CCIS (`2304.08253v2.pdf`) | MIND is mostly soft news: hard news (news plus finance) is 36% of all articles. Candidate selection shifts the category mix (lifestyle 4.4% → 17%), and how candidates are chosen is undocumented. In the large validation set, candidate lists average 37 items. | **Limitations section:** MIND's candidate generation is opaque, and the platform skews soft. This is a reason to report results **per category** (E3) and to describe our importance results as "for this platform". |
| **Xun et al., "Why Do We Click: Visual Impression-aware News Recommendation"**, ACM MM 2021 (`2109.12651v1.pdf`) | Clicks depend on the visual impression (layout plus image plus title). Builds IM-MIND and improves recommenders with visual-impression modelling. | **Limitations section:** text-only news values leave out visual cues, and MIND has no screen-position data. We note this and don't claim layout effects. |

## 2. Prior work on news values and engagement (cited by the papers above; not yet read)

- **Trilling, Tolochko & Burscher 2017**, *Journalism & Mass Communication Quarterly* 94(1): "From newsworthiness to shareworthiness". News factors predict **sharing** of Dutch news articles.
- **Lagerwerf & Govaert 2021**, Palgrave chapter, "Raising clickworthiness". Effects of foregrounding news values in online newspaper headlines on **CTR**. Our earlier search found a secondary report that only negativity raised CTR; check this in the chapter itself.
- **Park & Kaye 2021**, *Journalism*. News values and likes, comments and shares on Facebook.
- **Araujo & van der Meer 2020**, *Journalism* 21(5). News values and peaks of Twitter activity.
- **Piotrkowicz et al. 2017**, "Automatic Extraction of News Values from Headline Text" (EACL Student Research Workshop) and the companion ICWSM 2017 paper. Rule- and feature-based headline news values on The Guardian. The crowdsourced survey suggests news values affect clicks.
- **Harcup & O'Neill 2017**, *Journalism Studies* 18(12), "What is news? News values revisited (again)". Source of our value list.
- **Galtung & Ruge 1965**. The original news-value theory.
- **Bednarek & Caple 2017**, *The Discourse of News Values*. Discursive (text-construed) news values.

## 3. What is and isn't new about our study

**Not new, so don't claim it:**
- News values relate to engagement (Trilling 2017; Lagerwerf & Govaert 2021; Park & Kaye 2021).
- LLMs can annotate news values (Sotic & Kamps 2025, for images).

**Defensible claim, if the results come in:**
1. **Large scale and validated:** text news values for all 22,771 MIND-small candidate articles, scored by an open LLM and checked against two human labellers (reliability and validity for each value).
2. **An exposure-controlled test against real impression logs:** within-impression AUC and conditional logit. Earlier engagement studies used aggregate shares, likes or CTR, which mix appeal with how often an item was shown.
3. **Importance vs engagement on a recommender benchmark:** where public importance and clicks diverge, and in which categories. This links news-value theory to normative news recommendation (Meese & Herbertson 2025; Vrijenhoek 2023).

**Suggested wording:** "To our knowledge, this is the first study to relate LLM-annotated textual news values to click behaviour in MIND impression logs under a within-impression design."

**Before submitting:** run one more search (Google Scholar: "news values" MIND clicks; "newsworthiness" LLM click-through), and check the Lagerwerf & Govaert chapter so we describe it correctly.

## 4. Novelty search (2026-11-16)
Three web searches: "news values" LLM annotation click-through MIND; newsworthiness LLM clicks; and the Lagerwerf & Govaert chapter.
- **No study found** that relates LLM-annotated **textual** news values to clicks in MIND impression logs. The closest is still Sotic & Kamps (TPDL 2025), which covers images and doesn't test clicks.
- **Adjacent work, citable as context:**
  - LOLA (arXiv 2406.02611): LLMs predicting the more clickable headline on Upworthy A/B tests. This is click prediction, not news values.
  - CherryRec (arXiv 2406.12243): a hand-built value model for filtering news. It isn't news-value theory and isn't validated against clicks.
  - LLM-Assisted Reranking (arXiv 2606.02883): YouTube, not MIND.
- **Lagerwerf & Govaert:** the chapter "Raising Clickworthiness: Effects of Foregrounding News Values in Online Newspaper Headlines" appears in an edited volume on news values from an audience perspective (Palgrave). A secondary source describes 4,000 Dutch headlines and says only Negativity raised CTR. **Still unverified at first hand:** cite it as "headline news values and CTR in Dutch newspapers", and add the negativity detail only after checking the chapter.
- **Piotrkowicz et al., ICWSM 2017**, "The Impact of News Values and Linguistic Style on the Popularity of Headlines on Twitter and Facebook". The page was bot-blocked, so details are unverified. Cite only as existing work on headline news values and social popularity.
- **Not done:** Google Scholar itself (it can't be automated here). Run it by hand before submitting.
