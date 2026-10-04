// Floodlit design tokens (spec §30). Values are proposals; verify every text pair at WCAG AA before handoff.

export type Palette = {
  bg: string;
  surface: string;
  surface2: string;
  ink: string;
  ink2: string;
  hairline: string;
  highlight: string;
  onHighlight: string;
  impact: string;
  sports: string;
  film: string;
  general: string;
  toneNeutral: string;
  tonePositive: string;
  toneNegative: string;
  scrim: string;
};

export const light: Palette = {
  bg: '#F6F7F9',
  surface: '#FFFFFF',
  surface2: '#EEF1F5',
  ink: '#0F1B2D',
  ink2: '#4A5568',
  hairline: '#DCE1E8',
  highlight: '#FFD23F',
  onHighlight: '#0F1B2D',
  impact: '#C62A2F',
  sports: '#1E7F4A',
  film: '#B8327F',
  general: '#5B6B82',
  toneNeutral: '#8A96A8',
  tonePositive: '#1F9E8A',
  toneNegative: '#E0765C',
  scrim: 'rgba(15,27,45,0.45)',
};

export const dark: Palette = {
  bg: '#0F1B2D',
  surface: '#172741',
  surface2: '#1E3150',
  ink: '#F2F5F9',
  ink2: '#A7B4C7',
  hairline: '#2A3D5C',
  highlight: '#FFD23F',
  onHighlight: '#0F1B2D',
  impact: '#FF6369',
  sports: '#3CCB7F',
  film: '#F06BB8',
  general: '#8FA0B8',
  toneNeutral: '#7D8BA0',
  tonePositive: '#4FD1BC',
  toneNegative: '#FF8F75',
  scrim: 'rgba(0,0,0,0.6)',
};

// 4 pt grid
export const space = { xs: 4, sm: 8, md: 12, lg: 16, xl: 20, xxl: 28, gutter: 16 } as const;

export const radius = { card: 14, sheet: 20, button: 12, badge: 6, chip: 999 } as const;

export const fonts = {
  head600: 'BarlowSemiCondensed_600SemiBold',
  head700: 'BarlowSemiCondensed_700Bold',
  body400: 'AtkinsonHyperlegible_400Regular',
  body700: 'AtkinsonHyperlegible_700Bold',
} as const;

// size / line height in pt (spec §30 typography table)
export const type = {
  flashHeadline: { fontFamily: fonts.head600, fontSize: 26, lineHeight: 30 },
  storyHeadline: { fontFamily: fonts.head700, fontSize: 28, lineHeight: 32 },
  heroHeadline: { fontFamily: fonts.head700, fontSize: 26, lineHeight: 30 },
  screenTitle: { fontFamily: fonts.head700, fontSize: 30, lineHeight: 34 },
  sectionTitle: { fontFamily: fonts.head600, fontSize: 20, lineHeight: 24 },
  cardHeadline: { fontFamily: fonts.head600, fontSize: 20, lineHeight: 24 },
  compactHeadline: { fontFamily: fonts.head600, fontSize: 17, lineHeight: 22 },
  summary: { fontFamily: fonts.body400, fontSize: 17, lineHeight: 26 },
  flashSummary: { fontFamily: fonts.body400, fontSize: 16, lineHeight: 23 },
  storySummary: { fontFamily: fonts.body400, fontSize: 18, lineHeight: 28 },
  body: { fontFamily: fonts.body400, fontSize: 16, lineHeight: 22 },
  why: { fontFamily: fonts.body700, fontSize: 15, lineHeight: 20 },
  meta: { fontFamily: fonts.body400, fontSize: 13, lineHeight: 18 },
  metaBold: { fontFamily: fonts.body700, fontSize: 13, lineHeight: 18 },
  label: { fontFamily: fonts.body700, fontSize: 12, lineHeight: 16, letterSpacing: 0.2 },
  button: { fontFamily: fonts.body700, fontSize: 16, lineHeight: 20 },
} as const;

export type TypeVariant = keyof typeof type;
