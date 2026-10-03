// Small shared building blocks: chips, segmented control, pills, skeletons, empty and error states, headers.
import { ReactNode, useEffect, useRef } from 'react';
import { AccessibilityInfo, Animated, Pressable, StyleProp, View, ViewStyle } from 'react-native';
import { router } from 'expo-router';

import { radius, space } from '@/theme/tokens';
import { useTheme } from '@/theme/useTheme';
import { Button } from './Button';
import { Glyph, GlyphName } from './Glyph';
import { Txt } from './Txt';

export function Chip({
  label, selected, onPress, icon, trailing, accessibilityHint, forceDark,
}: {
  label: string; selected?: boolean; onPress?: () => void; icon?: GlyphName; trailing?: ReactNode;
  accessibilityHint?: string; forceDark?: boolean;
}) {
  const { c } = useTheme({ forceDark });
  return (
    <Pressable
      onPress={onPress}
      disabled={!onPress}
      accessibilityRole={onPress ? 'button' : 'text'}
      accessibilityState={{ selected: !!selected }}
      accessibilityHint={accessibilityHint}
      hitSlop={6}
      style={({ pressed }) => ({
        minHeight: 36, paddingHorizontal: 14, borderRadius: radius.chip, borderWidth: 1.5,
        borderColor: selected ? c.ink : c.hairline, backgroundColor: selected ? c.ink : c.surface,
        flexDirection: 'row', alignItems: 'center', gap: 6, opacity: pressed ? 0.7 : 1,
      })}
    >
      {icon && <Glyph name={icon} size={15} color={selected ? c.bg : c.ink} />}
      <Txt v="metaBold" color={selected ? c.bg : c.ink}>{label}</Txt>
      {trailing}
    </Pressable>
  );
}

export function Segmented<T extends string | number>({
  options, value, onChange, label,
}: { options: { label: string; value: T }[]; value: T; onChange: (v: T) => void; label: string }) {
  const { c } = useTheme();
  return (
    <View accessibilityRole="radiogroup" accessibilityLabel={label}
      style={{ flexDirection: 'row', backgroundColor: c.surface2, borderRadius: radius.button, padding: 3 }}>
      {options.map((o) => {
        const on = o.value === value;
        return (
          <Pressable key={String(o.value)} onPress={() => onChange(o.value)} accessibilityRole="radio"
            accessibilityState={{ checked: on }}
            style={{ flex: 1, minHeight: 40, alignItems: 'center', justifyContent: 'center', borderRadius: radius.button - 3, backgroundColor: on ? c.surface : 'transparent' }}>
            <Txt v="metaBold" color={on ? c.ink : c.ink2}>{o.label}</Txt>
          </Pressable>
        );
      })}
    </View>
  );
}

export function Pill({ label, kind, forceDark }: { label: string; kind: 'must' | 'neutral' | 'impactOutline' | 'impactFilled' | 'breaking' | 'explore'; forceDark?: boolean }) {
  const { c } = useTheme({ forceDark });
  if (kind === 'breaking')
    return (
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 5 }}>
        <View style={{ width: 7, height: 7, borderRadius: 4, backgroundColor: c.impact }} />
        <Txt v="label" color={c.impact}>{label}</Txt>
      </View>
    );
  const style: ViewStyle = { paddingHorizontal: 8, paddingVertical: 3, borderRadius: radius.badge, alignSelf: 'flex-start' };
  if (kind === 'must') return <View style={[style, { backgroundColor: c.highlight }]}><Txt v="label" color={c.onHighlight}>{label}</Txt></View>;
  if (kind === 'impactFilled') return <View style={[style, { backgroundColor: c.impact }]}><Txt v="label" color="#fff">{label}</Txt></View>;
  if (kind === 'impactOutline') return <View style={[style, { borderWidth: 1.5, borderColor: c.impact }]}><Txt v="label" color={c.impact}>{label}</Txt></View>;
  return <View style={[style, { paddingHorizontal: 0 }]}><Txt v="label" color={c.ink2}>{label}</Txt></View>;
}

export function Skeleton({ h = 16, w = '100%', style }: { h?: number; w?: number | `${number}%`; style?: StyleProp<ViewStyle> }) {
  const { c } = useTheme();
  const o = useRef(new Animated.Value(0.5)).current;
  useEffect(() => {
    let loop: Animated.CompositeAnimation | null = null;
    AccessibilityInfo.isReduceMotionEnabled().then((reduce) => {
      if (reduce) return; // shimmer stops under reduce motion
      loop = Animated.loop(Animated.sequence([
        Animated.timing(o, { toValue: 1, duration: 700, useNativeDriver: true }),
        Animated.timing(o, { toValue: 0.5, duration: 700, useNativeDriver: true }),
      ]));
      loop.start();
    });
    return () => loop?.stop();
  }, [o]);
  return <Animated.View style={[{ height: h, width: w, borderRadius: 6, backgroundColor: c.surface2, opacity: o }, style]} />;
}

export function CardSkeleton() {
  const { c } = useTheme();
  return (
    <View accessibilityLabel="Loading" style={{ backgroundColor: c.surface, borderRadius: radius.card, padding: space.lg, gap: 10, marginBottom: space.md }}>
      <Skeleton h={12} w={80} />
      <Skeleton h={20} w="90%" />
      <Skeleton h={14} w="70%" />
      <Skeleton h={12} w={120} />
    </View>
  );
}

// One sentence on why, plus one action (spec §29)
export function EmptyState({ text, action, onAction }: { text: string; action?: string; onAction?: () => void }) {
  const { c } = useTheme();
  return (
    <View style={{ backgroundColor: c.surface, borderRadius: radius.card, padding: space.lg, gap: space.md, borderWidth: 1, borderColor: c.hairline }}>
      <Txt v="body" muted>{text}</Txt>
      {action && onAction && <Button label={action} variant="secondary" small onPress={onAction} style={{ alignSelf: 'flex-start' }} />}
    </View>
  );
}

export function InlineError({ text, onRetry }: { text: string; onRetry?: () => void }) {
  const { c } = useTheme();
  return (
    <View accessibilityLiveRegion="polite" style={{ flexDirection: 'row', alignItems: 'center', gap: 12, backgroundColor: c.surface2, borderRadius: radius.card, padding: space.md }}>
      <Txt v="meta" style={{ flex: 1 }}>{text}</Txt>
      {onRetry && <Button label="Retry" variant="secondary" small onPress={onRetry} />}
    </View>
  );
}

export function Banner({ text, action, onAction }: { text: string; action?: string; onAction?: () => void }) {
  const { c } = useTheme();
  return (
    <View accessibilityLiveRegion="polite" style={{ backgroundColor: c.ink, paddingHorizontal: space.lg, paddingVertical: 10, flexDirection: 'row', alignItems: 'center', gap: 12 }}>
      <Txt v="meta" color={c.bg} style={{ flex: 1 }}>{text}</Txt>
      {action && <Pressable onPress={onAction} hitSlop={10}><Txt v="metaBold" color={c.highlight}>{action}</Txt></Pressable>}
    </View>
  );
}

export function SectionTitle({ title, sub, right }: { title: string; sub?: string; right?: ReactNode }) {
  return (
    <View style={{ marginTop: space.xxl, marginBottom: space.md, flexDirection: 'row', alignItems: 'flex-end' }}>
      <View style={{ flex: 1 }}>
        <Txt v="sectionTitle" accessibilityRole="header">{title}</Txt>
        {sub && <Txt v="meta" muted>{sub}</Txt>}
      </View>
      {right}
    </View>
  );
}

// Pushed screens: back button + title, tab bar hidden
export function TopBar({ title, right, forceDark, onBack }: { title?: string; right?: ReactNode; forceDark?: boolean; onBack?: () => void }) {
  const { c } = useTheme({ forceDark });
  return (
    <View style={{ flexDirection: 'row', alignItems: 'center', height: 52, paddingHorizontal: space.sm, borderBottomWidth: 1, borderBottomColor: c.hairline, backgroundColor: c.bg }}>
      <Pressable onPress={onBack ?? (() => (router.canGoBack() ? router.back() : router.replace('/(tabs)')))} accessibilityRole="button" accessibilityLabel="Back" hitSlop={10}
        style={{ width: 44, height: 44, alignItems: 'center', justifyContent: 'center' }}>
        <Glyph name="back" size={22} color={c.ink} />
      </Pressable>
      <Txt v="metaBold" numberOfLines={1} style={{ flex: 1, textAlign: 'center' }} color={c.ink}>{title}</Txt>
      <View style={{ minWidth: 44, flexDirection: 'row', justifyContent: 'flex-end' }}>{right}</View>
    </View>
  );
}

export function IconButton({ icon, label, onPress, color, filled, size = 22 }: { icon: GlyphName; label: string; onPress: () => void; color?: string; filled?: boolean; size?: number }) {
  const { c } = useTheme();
  return (
    <Pressable onPress={onPress} accessibilityRole="button" accessibilityLabel={label} hitSlop={8}
      style={{ width: 44, height: 44, alignItems: 'center', justifyContent: 'center' }}>
      <Glyph name={icon} size={size} color={color ?? c.ink} filled={filled} />
    </Pressable>
  );
}

export function Row({ title, sub, onPress, right }: { title: string; sub?: string; onPress?: () => void; right?: ReactNode }) {
  const { c } = useTheme();
  return (
    <Pressable onPress={onPress} disabled={!onPress} accessibilityRole={onPress ? 'button' : undefined}
      style={({ pressed }) => ({ minHeight: 56, paddingVertical: 10, flexDirection: 'row', alignItems: 'center', gap: 12, borderBottomWidth: 1, borderBottomColor: c.hairline, opacity: pressed ? 0.7 : 1 })}>
      <View style={{ flex: 1 }}>
        <Txt v="body">{title}</Txt>
        {sub && <Txt v="meta" muted>{sub}</Txt>}
      </View>
      {right ?? (onPress && <Glyph name="chevron" color={c.ink2} />)}
    </Pressable>
  );
}

export function Progress({ step, total }: { step: number; total: number }) {
  const { c } = useTheme();
  return (
    <View accessibilityLabel={`Step ${step} of ${total}`} style={{ flexDirection: 'row', gap: 4 }}>
      {Array.from({ length: total }).map((_, i) => (
        <View key={i} style={{ flex: 1, height: 4, borderRadius: 2, backgroundColor: i < step ? c.ink : c.hairline }} />
      ))}
    </View>
  );
}
