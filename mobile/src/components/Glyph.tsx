// Line glyphs drawn with react-native-svg so the app needs no icon font.
import Svg, { Circle, Path, Rect } from 'react-native-svg';

export type GlyphName =
  | 'ball' | 'film' | 'globe' | 'person' | 'link' | 'echo' | 'compass' | 'spotlight' | 'stack' | 'bell'
  | 'search' | 'dots' | 'back' | 'close' | 'chevron' | 'home' | 'flash' | 'insights' | 'profile' | 'ask'
  | 'check' | 'heart' | 'skip' | 'undo' | 'share' | 'bookmark' | 'plus' | 'gear' | 'alert'
  | 'thumbUp' | 'thumbDown' | 'comment' | 'forward';

type Props = { name: GlyphName; size?: number; color: string; filled?: boolean };

export function Glyph({ name, size = 18, color, filled }: Props) {
  const p = { stroke: color, strokeWidth: 1.8, fill: 'none', strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const };
  const body = (() => {
    switch (name) {
      case 'ball':
        return (<><Circle cx={12} cy={12} r={9} {...p} /><Path d="M12 7l4 3-1.5 4.5h-5L8 10z M12 3v4 M21 10l-5 0 M3 10h5 M9.5 14.5L7 19 M14.5 14.5L17 19" {...p} /></>);
      case 'film':
        return (<><Rect x={3} y={4} width={18} height={16} rx={2} {...p} /><Path d="M7 4v16 M17 4v16 M3 9h4 M3 15h4 M17 9h4 M17 15h4" {...p} /></>);
      case 'globe':
        return (<><Circle cx={12} cy={12} r={9} {...p} /><Path d="M3 12h18 M12 3c3 3 3 15 0 18 M12 3c-3 3-3 15 0 18" {...p} /></>);
      case 'person':
        return (<><Circle cx={12} cy={8} r={4} {...p} /><Path d="M4 21c1-4 4-6 8-6s7 2 8 6" {...p} /></>);
      case 'link':
        return <Path d="M10 14a4 4 0 006 0l3-3a4 4 0 00-6-6l-1 1 M14 10a4 4 0 00-6 0l-3 3a4 4 0 006 6l1-1" {...p} />;
      case 'echo':
        return (<><Circle cx={9} cy={12} r={3} {...p} /><Path d="M14 8a6 6 0 010 8 M17 5a10 10 0 010 14" {...p} /></>);
      case 'compass':
        return (<><Circle cx={12} cy={12} r={9} {...p} /><Path d="M15.5 8.5l-2 5-5 2 2-5z" {...p} /></>);
      case 'spotlight':
        return <Path d="M8 3h8l-2 6h-4z M10 9l-5 12 M14 9l5 12 M5 21h14" {...p} />;
      case 'stack':
        return (<><Rect x={7} y={3} width={13} height={14} rx={2} {...p} /><Path d="M4 7v12a2 2 0 002 2h11" {...p} /></>);
      case 'bell':
        return <Path d="M6 16V11a6 6 0 0112 0v5l2 2H4z M10 20a2 2 0 004 0" {...p} />;
      case 'search':
        return (<><Circle cx={11} cy={11} r={7} {...p} /><Path d="M20 20l-4-4" {...p} /></>);
      case 'dots':
        return (<><Circle cx={5} cy={12} r={1.6} fill={color} /><Circle cx={12} cy={12} r={1.6} fill={color} /><Circle cx={19} cy={12} r={1.6} fill={color} /></>);
      case 'back':
        return <Path d="M15 5l-7 7 7 7" {...p} />;
      case 'chevron':
        return <Path d="M9 5l7 7-7 7" {...p} />;
      case 'close':
        return <Path d="M6 6l12 12 M18 6L6 18" {...p} />;
      case 'home':
        return <Path d="M4 11l8-7 8 7v9h-5v-6H9v6H4z" {...p} fill={filled ? color : 'none'} />;
      case 'flash':
        return (<><Rect x={5} y={3} width={14} height={18} rx={3} {...p} fill={filled ? color : 'none'} /><Path d="M9 8h6 M9 12h6" {...p} stroke={filled ? '#0F1B2D' : color} /></>);
      case 'insights':
        return <Path d="M4 20V10 M10 20V4 M16 20v-7 M22 20H2" {...p} />;
      case 'profile':
        return (<><Circle cx={12} cy={8} r={4} {...p} fill={filled ? color : 'none'} /><Path d="M4 21c1-4 4-6 8-6s7 2 8 6" {...p} /></>);
      case 'ask':
        return <Path d="M5 5h14a2 2 0 012 2v8a2 2 0 01-2 2h-7l-5 4v-4H5a2 2 0 01-2-2V7a2 2 0 012-2z M8 11h.01 M12 11h.01 M16 11h.01" {...p} />;
      case 'check':
        return <Path d="M5 12l5 5 9-10" {...p} />;
      case 'heart':
        return <Path d="M12 20s-7-4.5-7-10a4 4 0 017-2.5A4 4 0 0119 10c0 5.5-7 10-7 10z" {...p} fill={filled ? color : 'none'} />;
      case 'skip':
        return <Path d="M5 12h12 M13 7l5 5-5 5" {...p} />;
      case 'undo':
        return <Path d="M9 7L4 12l5 5 M4 12h11a5 5 0 010 10h-2" {...p} />;
      case 'share':
        return <Path d="M12 3v12 M7 8l5-5 5 5 M5 14v5a2 2 0 002 2h10a2 2 0 002-2v-5" {...p} />;
      case 'bookmark':
        return <Path d="M6 3h12v18l-6-4-6 4z" {...p} fill={filled ? color : 'none'} />;
      case 'plus':
        return <Path d="M12 5v14 M5 12h14" {...p} />;
      case 'gear':
        return (<><Circle cx={12} cy={12} r={3} {...p} /><Path d="M12 2v3 M12 19v3 M2 12h3 M19 12h3 M4.9 4.9l2.1 2.1 M17 17l2.1 2.1 M4.9 19.1L7 17 M17 7l2.1-2.1" {...p} /></>);
      case 'alert':
        return <Path d="M12 3l9 17H3z M12 10v4 M12 17h.01" {...p} />;
      case 'thumbUp':
        return (<><Path d="M7 10v11" {...p} /><Path d="M15 5.9L14 10h5.8a2 2 0 011.9 2.6l-2.3 8a2 2 0 01-1.9 1.4H4a2 2 0 01-2-2v-8a2 2 0 012-2h2.8a2 2 0 001.8-1.1L12 2a3.1 3.1 0 013 3.9z" {...p} fill={filled ? color : 'none'} /></>);
      case 'thumbDown':
        return (<><Path d="M17 14V3" {...p} /><Path d="M9 18.1L10 14H4.2a2 2 0 01-1.9-2.6l2.3-8A2 2 0 016.5 2H20a2 2 0 012 2v8a2 2 0 01-2 2h-2.8a2 2 0 00-1.8 1.1L12 22a3.1 3.1 0 01-3-3.9z" {...p} fill={filled ? color : 'none'} /></>);
      case 'comment':
        return <Path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z M8 9h8 M8 13h5" {...p} />;
      case 'forward':
        return <Path d="M15 17l5-5-5-5 M4 18v-2a4 4 0 014-4h12" {...p} />;
    }
  })();
  return (
    <Svg width={size} height={size} viewBox="0 0 24 24" accessibilityElementsHidden importantForAccessibility="no-hide-descendants">
      {body}
    </Svg>
  );
}

export function topicGlyph(topic?: string): GlyphName {
  return topic === 'sports' ? 'ball' : topic === 'entertainment_movies' ? 'film' : 'globe';
}

// 3 = Essential, 2 = Important, 1 = Interested
export function SignalBars({ level, color, dim }: { level: 1 | 2 | 3; color: string; dim: string }) {
  return (
    <Svg width={14} height={12} viewBox="0 0 14 12" accessibilityElementsHidden>
      {[0, 1, 2].map((i) => (
        <Rect key={i} x={i * 5} y={8 - i * 4} width={3.5} height={4 + i * 4} rx={1} fill={i < level ? color : dim} />
      ))}
    </Svg>
  );
}
