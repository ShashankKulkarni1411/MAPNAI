// The engine's profile sentences say "(high)" and "entertainment movies"; the UI says Essential and Film.
export function uiSentence(s: string): string {
  return s
    .replace(/\(high\)/g, '(Essential)')
    .replace(/\(medium\)/g, '(Important)')
    .replace(/\(low\)/g, '(Interested)')
    .replace(/entertainment[ _]movies/g, 'Film')
    .replace(/\bsports\b/g, 'Sports')
    .replace(/\bother\b/g, 'General');
}
