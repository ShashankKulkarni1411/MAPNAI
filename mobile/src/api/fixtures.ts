// Illustrative stories for mock mode (spec §24 examples). Not real reporting.
import type { EngineTopic, RiskLevel } from './types';

export type FixtureArticle = {
  id: string;
  title: string;
  topic: EngineTopic;
  topicTag?: string;
  source: string;
  ageH: number;
  m: number; // materiality 0..1
  risk: RiskLevel;
  unscored: boolean;
  sources: number;
  first: boolean;
  urgent?: boolean;
  entities: string[]; // entity keys
  summary: string | null;
  summaryLong?: string;
  body?: string;
  angle?: string;
  action?: string;
  factors?: [number, number, number, number];
};

export const ENTITIES: Record<string, { name: string; mentions: number }> = {
  'virat kohli': { name: 'Virat Kohli', mentions: 312 },
  'mumbai indians': { name: 'Mumbai Indians', mentions: 141 },
  'manchester city': { name: 'Manchester City', mentions: 128 },
  ipl: { name: 'IPL', mentions: 220 },
  'jasprit bumrah': { name: 'Jasprit Bumrah', mentions: 96 },
  'arshdeep singh': { name: 'Arshdeep Singh', mentions: 41 },
  'lando norris': { name: 'Lando Norris', mentions: 64 },
  'max verstappen': { name: 'Max Verstappen', mentions: 88 },
  'shah rukh khan': { name: 'Shah Rukh Khan', mentions: 150 },
  'yash raj films': { name: 'Yash Raj Films', mentions: 57 },
  cbfc: { name: 'CBFC', mentions: 33 },
  'netflix india': { name: 'Netflix India', mentions: 45 },
  atlee: { name: 'Atlee', mentions: 29 },
  jawan: { name: 'Jawan', mentions: 52 },
  'rohit sharma': { name: 'Rohit Sharma', mentions: 175 },
  'pep guardiola': { name: 'Pep Guardiola', mentions: 70 },
  'india test team': { name: 'India Test team', mentions: 110 },
  rodri: { name: 'Rodri', mentions: 38 },
  'shubman gill': { name: 'Shubman Gill', mentions: 81 },
  'rashid khan': { name: 'Rashid Khan', mentions: 47 },
  'gujarat titans': { name: 'Gujarat Titans', mentions: 39 },
  fifa: { name: 'FIFA', mentions: 120 },
  'siddharth anand': { name: 'Siddharth Anand', mentions: 22 },
  oscars: { name: 'Oscars', mentions: 60 },
};

// Co-mention links ("often mentioned with")
export const COMENTIONS: Record<string, string[]> = {
  'virat kohli': ['india test team', 'rohit sharma', 'jasprit bumrah'],
  'mumbai indians': ['rohit sharma', 'jasprit bumrah', 'ipl'],
  'manchester city': ['pep guardiola', 'rodri'],
  'shah rukh khan': ['jawan', 'atlee', 'yash raj films'],
  'yash raj films': ['cbfc', 'siddharth anand', 'shah rukh khan'],
  'lando norris': ['max verstappen'],
};

export const ARTICLES: FixtureArticle[] = [
  {
    id: 'a-kohli', title: 'Kohli ruled out of first Test with hamstring strain', topic: 'sports', source: 'BBC Sport',
    ageH: 2, m: 0.81, risk: 'ESCALATE', unscored: false, sources: 9, first: true, urgent: true,
    entities: ['virat kohli', 'india test team', 'rohit sharma'],
    summary: 'Scans show a tear; he misses Friday. India expect him back for the second Test in Adelaide.',
    summaryLong: 'Virat Kohli will miss the first Test after scans confirmed a hamstring strain. The team medical staff expect him back for the second Test in Adelaide. Shubman Gill is likely to move up the order.',
    angle: 'Sky Sports', action: "Watch Friday's team news for the replacement.", factors: [0.9, 0.85, 0.88, 0.6],
  },
  {
    id: 'a-mi-coach', title: 'Mumbai Indians appoint new bowling coach', topic: 'sports', source: 'ESPNcricinfo',
    ageH: 5, m: 0.53, risk: null, unscored: true, sources: 1, first: true,
    entities: ['mumbai indians', 'ipl'],
    summary: 'The franchise named a former Test seamer to lead its bowling unit before the auction.',
  },
  {
    id: 'a-rodri', title: 'Rodri back in full training', topic: 'sports', source: 'The Athletic',
    ageH: 7, m: 0.36, risk: 'MONITOR', unscored: false, sources: 4, first: false,
    entities: ['rodri', 'manchester city', 'pep guardiola'],
    summary: 'The midfielder trained with the squad for the first time since his knee injury.',
  },
  {
    id: 'a-bumrah', title: 'Bumrah ruled out of series opener with back spasms', topic: 'sports', source: 'BBC Sport',
    ageH: 1, m: 0.71, risk: 'ESCALATE', unscored: false, sources: 6, first: true, urgent: true,
    entities: ['jasprit bumrah', 'india test team', 'arshdeep singh'],
    summary: 'Jasprit Bumrah will miss the first match after scans showed back spasms. The team expects him back for the second game, with Arshdeep Singh in line to replace him.',
    angle: 'Cricbuzz', action: 'Check your fantasy line-up before the deadline.', factors: [0.8, 0.8, 0.9, 0.55],
  },
  {
    id: 'a-verstappen', title: 'Verstappen wins Japanese Grand Prix', topic: 'sports', source: 'Sky Sports',
    ageH: 3, m: 0.4, risk: 'MONITOR', unscored: false, sources: 10, first: false,
    entities: ['max verstappen', 'lando norris'],
    summary: 'Verstappen led from lights to flag at Suzuka; Norris finished second after a late charge.',
  },
  {
    id: 'a-ipl-auction', title: 'IPL auction date announced', topic: 'sports', source: 'Times of India',
    ageH: 9, m: 0.53, risk: null, unscored: true, sources: 3, first: false,
    entities: ['ipl', 'mumbai indians', 'gujarat titans'],
    summary: 'The player auction will be held in Jeddah in late November, with a purse of ₹120 crore per team.',
  },
  {
    id: 'a-rohit', title: 'Rohit Sharma on the captaincy talk', topic: 'sports', source: 'NDTV Sports',
    ageH: 11, m: 0.27, risk: 'MONITOR', unscored: false, sources: 2, first: false,
    entities: ['rohit sharma', 'mumbai indians'],
    summary: 'Rohit said he was focused on the series and would not discuss leadership plans.',
  },
  {
    id: 'a-jawan', title: 'Jawan sequel confirmed', topic: 'entertainment_movies', source: 'Variety India',
    ageH: 6, m: 0.47, risk: null, unscored: true, sources: 5, first: true,
    entities: ['jawan', 'atlee', 'shah rukh khan'],
    summary: 'Atlee confirmed a sequel is in development, with Shah Rukh Khan returning in the lead.',
  },
  {
    id: 'a-cbfc', title: "CBFC asks for cuts in YRF's next release; date at risk", topic: 'entertainment_movies',
    source: 'Bollywood Hungama', ageH: 4, m: 0.71, risk: 'ALERT', unscored: false, sources: 6, first: true,
    entities: ['yash raj films', 'cbfc', 'siddharth anand'],
    summary: 'The certification board has asked for three cuts. The studio says the release date may move.',
    angle: 'Film Companion', action: 'Watch for a revised release date from the studio.', factors: [0.7, 0.75, 0.7, 0.5],
  },
  {
    id: 'a-oscar', title: "India's Oscar entry named", topic: 'entertainment_movies', source: 'The Hindu',
    ageH: 8, m: 0.62, risk: 'ALERT', unscored: false, sources: 14, first: false, entities: ['oscars'],
    summary: 'The Film Federation of India picked a Malayalam drama as the country’s official entry.',
  },
  {
    id: 'a-wc-draw', title: 'World Cup draw sets the groups', topic: 'sports', source: 'Reuters',
    ageH: 10, m: 0.66, risk: 'ALERT', unscored: false, sources: 21, first: false, entities: ['fifa'],
    summary: 'Hosts were placed in Group A; two former champions meet in the group stage.',
  },
  {
    id: 'a-srk-brand', title: 'Shah Rukh Khan signs new watch endorsement', topic: 'entertainment_movies',
    source: 'Mint', ageH: 14, m: 0.22, risk: 'MONITOR', unscored: false, sources: 2, first: false,
    entities: ['shah rukh khan'], summary: 'The multi-year deal makes him the face of the brand in Asia.',
  },
  {
    id: 'a-netflix', title: 'Netflix India slate adds four originals', topic: 'entertainment_movies',
    source: 'Hollywood Reporter India', ageH: 13, m: 0.35, risk: null, unscored: true, sources: 3, first: false,
    entities: ['netflix india'], summary: null,
    body: 'Netflix India announced four new original films for next year, including two thrillers and a period drama produced with regional studios. The service said the slate reflects growing demand for…',
  },
  {
    id: 'a-gill', title: 'Gill to open in first Test', topic: 'sports', source: 'Cricbuzz', ageH: 3, m: 0.44,
    risk: 'MONITOR', unscored: false, sources: 5, first: false, entities: ['shubman gill', 'india test team', 'virat kohli'],
    summary: 'With Kohli out, Shubman Gill is set to open alongside the captain.',
  },
  {
    id: 'a-rashid', title: 'Rashid Khan named Gujarat Titans vice-captain', topic: 'sports', source: 'ESPNcricinfo',
    ageH: 12, m: 0.53, risk: null, unscored: true, sources: 2, first: true, entities: ['rashid khan', 'gujarat titans'],
    summary: 'The leg-spinner takes the role for the coming season.',
  },
  {
    id: 'a-norris-pole', title: 'Norris on pole at Suzuka', topic: 'sports', source: 'Autosport', ageH: 30, m: 0.38,
    risk: 'MONITOR', unscored: false, sources: 7, first: true, entities: ['lando norris', 'max verstappen'],
    summary: 'Norris beat Verstappen by 0.04 seconds in qualifying.',
  },
  {
    id: 'a-chip', title: 'Chipmaker unveils new phone processor', topic: 'other', topicTag: 'Technology',
    source: 'The Verge', ageH: 6, m: 0.5, risk: null, unscored: true, sources: 8, first: false, entities: [],
    summary: null,
    body: 'The company said its new processor is 30 percent faster than last year’s model and will ship in phones from early next year. Analysts expect the launch to…',
  },
  {
    id: 'a-guardiola', title: 'Guardiola praises academy graduates', topic: 'sports', source: 'Manchester Evening News',
    ageH: 16, m: 0.25, risk: 'MONITOR', unscored: false, sources: 2, first: false, entities: ['pep guardiola', 'manchester city'],
    summary: 'The City manager said two teenagers will travel with the first team.',
  },
];
