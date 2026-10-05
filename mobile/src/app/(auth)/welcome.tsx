// A1 Welcome: the product's value at a glance, with static sample story cards. Always light and editorial.
import { Image } from 'expo-image';
import { router, useFocusEffect } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { useCallback, useState } from 'react';
import { NativeScrollEvent, NativeSyntheticEvent, Pressable, ScrollView, useWindowDimensions, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import Svg, { Defs, LinearGradient, Rect, Stop } from 'react-native-svg';

import { Glyph, GlyphName } from '@/components/Glyph';
import { Txt } from '@/components/Txt';
import { fonts } from '@/theme/tokens';

// Welcome-only palette: warm white canvas, charcoal ink, pastel category tints.
const W = {
  bg: '#F7F6F3',
  ink: '#16171A',
  ink2: '#6B6E75',
  soft: '#ECEAE5',
  dot: '#D3D0CA',
};

type Sample = {
  id: string;
  image: number;
  topic: 'Football' | 'Film';
  icon: GlyphName;
  tint: { bg: string; fg: string };
  badge?: string;
  headline: string;
  summary: string;
  source: string;
  sources: number;
  ago: string;
};

const SPORT = { bg: '#DDEFE2', fg: '#1F5F3B' };
const FILM = { bg: '#F4E1EC', fg: '#8A2E62' };

const SAMPLES: Sample[] = [
  {
    id: 'ucl', image: require('../../../assets/welcome/stadium.jpg'), topic: 'Football', icon: 'ball', tint: SPORT, badge: 'Major',
    headline: 'Champions League group stage draw sets up blockbuster fixtures',
    summary: 'European giants face off in a highly anticipated draw, with several rematches from last season.',
    source: 'ESPN', sources: 5, ago: '2h ago',
  },
  {
    id: 'dune', image: require('../../../assets/welcome/dunes.jpg'), topic: 'Film', icon: 'film', tint: FILM, badge: 'Trending',
    headline: 'Dune: Part Three takes the next step toward its global release',
    summary: 'The studio locks a December window as the cast gathers for the first look in Abu Dhabi.',
    source: 'Variety', sources: 7, ago: '4h ago',
  },
  {
    id: 'cinema', image: require('../../../assets/welcome/cinema.jpg'), topic: 'Film', icon: 'film', tint: FILM,
    headline: 'Independent cinemas post their strongest summer in a decade',
    summary: 'Repertory screenings and event releases pulled younger audiences back to smaller screens.',
    source: 'The Guardian', sources: 4, ago: '6h ago',
  },
  {
    id: 'derby', image: require('../../../assets/welcome/pitch.jpg'), topic: 'Football', icon: 'ball', tint: SPORT,
    headline: 'Late winner settles a tense north London derby',
    summary: 'A stoppage-time header lifts the home side into the top four after a scrappy second half.',
    source: 'BBC Sport', sources: 9, ago: '8h ago',
  },
];

export default function Welcome() {
  const insets = useSafeAreaInsets();
  const { width, height } = useWindowDimensions();
  const [active, setActive] = useState(0);
  const [saved, setSaved] = useState<Record<string, boolean>>({});
  // The root layout sets the status bar from the app theme; this screen is always light, so own it while focused.
  const [focused, setFocused] = useState(false);
  useFocusEffect(useCallback(() => { setFocused(true); return () => setFocused(false); }, []));

  // Everything scales from the window so small Androids and large iPhones keep the same composition.
  const contentW = Math.min(width, 560);
  const gutter = contentW < 360 ? 16 : 20;
  // Hero is a clean photo block (no overlays) that runs under the status bar. The photo is cover-fitted:
  // aspect ratio kept, excess cropped. Bias the crop slightly above centre so the skyline stays in frame.
  const heroH = Math.round(Math.min(Math.max(height * 0.32, 230), 400));
  const headSize = Math.round(Math.min(Math.max(contentW * 0.074, 24), 32));
  const cardGap = 12;
  const cardW = Math.round(contentW - gutter * 2 - 36); // leave the next card peeking on the right
  const cardH = Math.round(Math.min(Math.max(height * 0.29, 210), 290));
  const compact = height < 700;

  const onScroll = (e: NativeSyntheticEvent<NativeScrollEvent>) => {
    const i = Math.round(e.nativeEvent.contentOffset.x / (cardW + cardGap));
    if (i !== active) setActive(Math.max(0, Math.min(SAMPLES.length - 1, i)));
  };

  return (
    <View style={{ flex: 1, backgroundColor: W.bg }}>
      {focused && <StatusBar style="dark" />}

      <ScrollView style={{ flex: 1 }} contentContainerStyle={{ paddingBottom: 8 }}
        showsVerticalScrollIndicator={false} bounces={false}>
        {/* Hero: crisp, unfiltered skyline with the brand row floating on the sky */}
        <View style={{ height: heroH, overflow: 'hidden', backgroundColor: '#C9C3D8' }}>
          <Image source={require('../../../assets/welcome/skyline.png')} accessible={false}
            style={{ position: 'absolute', top: 0, left: 0, right: 0, bottom: 0 }} contentFit="cover" contentPosition={{ top: '45%', left: '50%' }} />
          <View style={{ width: contentW, alignSelf: 'center', marginTop: insets.top + 10, paddingHorizontal: gutter, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' }}>
            <Txt accessibilityRole="header" color={W.ink} style={{ fontFamily: fonts.body700, fontSize: 13, lineHeight: 16, letterSpacing: 5 }}>MAPNAI</Txt>
            <Pressable onPress={() => router.push('/settings/appearance')} accessibilityRole="button" accessibilityLabel="Settings" hitSlop={10}
              style={({ pressed }) => ({ width: 34, height: 34, borderRadius: 17, alignItems: 'center', justifyContent: 'center', backgroundColor: 'rgba(255,255,255,0.5)', opacity: pressed ? 0.7 : 1 })}>
              <Glyph name="gear" size={16} color={W.ink} />
            </Pressable>
          </View>
        </View>

        <View style={{ width: contentW, alignSelf: 'center', paddingHorizontal: gutter, marginTop: compact ? 18 : 24 }}>
          <Txt color={W.ink} accessibilityRole="header" style={{ fontFamily: fonts.head700, fontSize: headSize, lineHeight: Math.round(headSize * 1.1), letterSpacing: -0.2, maxWidth: 420 }}>
            Know what matters in sports and film, and why.
          </Txt>
          <Txt color={W.ink2} style={{ fontFamily: fonts.body400, fontSize: 15, lineHeight: 21, marginTop: 8, maxWidth: 320 }}>
            Personalised stories, deeper context, smarter perspectives.
          </Txt>
        </View>

        <ScrollView horizontal showsHorizontalScrollIndicator={false} decelerationRate="fast" snapToInterval={cardW + cardGap} snapToAlignment="start"
          disableIntervalMomentum onScroll={onScroll} scrollEventThrottle={32}
          style={{ marginTop: compact ? 18 : 20, flexGrow: 0 }}
          contentContainerStyle={{ paddingHorizontal: gutter + (width - contentW) / 2, gap: cardGap }}
          accessibilityLabel="Example stories">
          {SAMPLES.map((s) => (
            <StoryCard key={s.id} s={s} width={cardW} height={cardH} showSummary={!compact} saved={!!saved[s.id]}
              onSave={() => setSaved((m) => ({ ...m, [s.id]: !m[s.id] }))} />
          ))}
        </ScrollView>

        <View style={{ flexDirection: 'row', justifyContent: 'center', alignItems: 'center', gap: 6, marginTop: 12 }}
          accessibilityLabel={`Story ${active + 1} of ${SAMPLES.length}`}>
          {SAMPLES.map((s, i) => (
            <View key={s.id} style={{ width: i === active ? 14 : 5, height: 5, borderRadius: 3, backgroundColor: i === active ? W.ink : W.dot }} />
          ))}
        </View>
      </ScrollView>

      <View style={{ width: contentW, alignSelf: 'center', paddingHorizontal: gutter, paddingTop: 8, paddingBottom: Math.max(insets.bottom, 12) + 4, gap: 8 }}>
        <Pressable onPress={() => router.push('/(auth)/create')} accessibilityRole="button" accessibilityLabel="Get started"
          style={({ pressed }) => ({ height: 52, borderRadius: 26, backgroundColor: W.ink, alignItems: 'center', justifyContent: 'center', opacity: pressed ? 0.85 : 1 })}>
          <Txt color="#FFFFFF" style={{ fontFamily: fonts.body700, fontSize: 16, lineHeight: 20 }}>Get started</Txt>
          <View style={{ position: 'absolute', right: 22 }}><Glyph name="skip" size={18} color="#FFFFFF" /></View>
        </Pressable>
        <Pressable onPress={() => router.push('/(auth)/sign-in')} accessibilityRole="button"
          style={({ pressed }) => ({ height: 46, borderRadius: 23, backgroundColor: W.soft, alignItems: 'center', justifyContent: 'center', opacity: pressed ? 0.7 : 1 })}>
          <Txt color={W.ink} style={{ fontFamily: fonts.body400, fontSize: 15, lineHeight: 20 }}>I have an account</Txt>
        </Pressable>
      </View>
    </View>
  );
}

// Full-bleed photo card; a dark scrim over the lower part of the card's own photo carries the copy.
function StoryCard({ s, width, height, showSummary, saved, onSave }: { s: Sample; width: number; height: number; showSummary: boolean; saved: boolean; onSave: () => void }) {
  return (
    <View accessible accessibilityLabel={`Example story. ${s.topic}. ${s.headline}. ${s.source}, ${s.sources} sources, ${s.ago}`}
      style={{ width, height, borderRadius: 20, overflow: 'hidden', backgroundColor: '#1E1F23' }}>
      <Image source={s.image} style={{ position: 'absolute', top: 0, left: 0, right: 0, bottom: 0 }} contentFit="cover" transition={150} accessible={false} />
      <Svg style={{ position: 'absolute', left: 0, right: 0, bottom: 0 }} width="100%" height={Math.round(height * 0.75)}>
        <Defs>
          <LinearGradient id={`scrim-${s.id}`} x1="0" y1="0" x2="0" y2="1">
            <Stop offset="0" stopColor="#0E0F12" stopOpacity={0} />
            <Stop offset="0.4" stopColor="#0E0F12" stopOpacity={0.6} />
            <Stop offset="1" stopColor="#0E0F12" stopOpacity={0.9} />
          </LinearGradient>
        </Defs>
        <Rect x="0" y="0" width="100%" height="100%" fill={`url(#scrim-${s.id})`} />
      </Svg>
      <Pressable onPress={onSave} accessibilityRole="button" accessibilityLabel={saved ? 'Remove bookmark' : 'Bookmark'} accessibilityState={{ selected: saved }} hitSlop={8}
        style={({ pressed }) => ({ position: 'absolute', top: 12, right: 12, width: 32, height: 32, borderRadius: 16, alignItems: 'center', justifyContent: 'center', backgroundColor: 'rgba(14,15,18,0.55)', opacity: pressed ? 0.7 : 1 })}>
        <Glyph name="bookmark" size={14} color="#FFFFFF" filled={saved} />
      </Pressable>
      <View style={{ position: 'absolute', left: 16, right: 16, bottom: 14, gap: 6 }}>
        <View style={{ flexDirection: 'row', gap: 6, marginBottom: 2 }}>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 5, backgroundColor: s.tint.bg, borderRadius: 999, paddingHorizontal: 9, height: 22 }}>
            <Glyph name={s.icon} size={11} color={s.tint.fg} />
            <Txt color={s.tint.fg} style={{ fontFamily: fonts.body700, fontSize: 11.5, lineHeight: 15 }}>{s.topic}</Txt>
          </View>
          {s.badge && (
            <View style={{ justifyContent: 'center', backgroundColor: 'rgba(14,15,18,0.55)', borderRadius: 999, paddingHorizontal: 9, height: 22 }}>
              <Txt color="#FFFFFF" style={{ fontFamily: fonts.body400, fontSize: 11.5, lineHeight: 15 }}>{s.badge}</Txt>
            </View>
          )}
        </View>
        <Txt color="#FFFFFF" numberOfLines={2} style={{ fontFamily: fonts.head700, fontSize: 19, lineHeight: 22 }}>{s.headline}</Txt>
        {showSummary && <Txt color="rgba(255,255,255,0.78)" numberOfLines={2} style={{ fontFamily: fonts.body400, fontSize: 13, lineHeight: 18 }}>{s.summary}</Txt>}
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8, marginTop: 4 }}>
          <View style={{ width: 18, height: 18, borderRadius: 9, backgroundColor: '#FFFFFF', alignItems: 'center', justifyContent: 'center' }}>
            <Txt color={W.ink} style={{ fontFamily: fonts.body700, fontSize: 9, lineHeight: 11 }}>{s.source[0]}</Txt>
          </View>
          <Txt color="#FFFFFF" numberOfLines={1} style={{ fontFamily: fonts.body700, fontSize: 12, lineHeight: 16 }}>{s.source}</Txt>
          <Txt color="rgba(255,255,255,0.65)" numberOfLines={1} style={{ fontFamily: fonts.body400, fontSize: 12, lineHeight: 16, flexShrink: 1 }}>
            {s.sources} sources · {s.ago}
          </Txt>
        </View>
      </View>
    </View>
  );
}
