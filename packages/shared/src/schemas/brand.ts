import { z } from 'zod';
import { HEX_COLOR_RE, contrastRatio } from './colorContrast';

// Mirrors services/langgraph/agency/artifacts/brand.py. brand_core is the
// canonical brand object every rendering derives from; color, typography,
// and motion are described qualitatively here, not as literal tokens --
// design_token_set compiles this into implementable values downstream.

// Below this, two brand colors don't read as distinct roles -- a design-
// quality heuristic this project chose, not a WCAG-defined metric. Keep in
// sync with MINIMUM_COLOR_STORY_DISTINCTION_RATIO in brand.py.
export const MINIMUM_COLOR_STORY_DISTINCTION_RATIO = 1.5;

export const LOGO_LOCKUP_TYPES = [
  'primary',
  'secondary',
  'icon_only',
  'wordmark',
  'horizontal',
  'stacked',
  'reversed',
  'monochrome'
] as const;

export const LogoLockupTypeSchema = z.enum(LOGO_LOCKUP_TYPES);

export const LogoLockupSchema = z.object({
  lockup_id: z.string().min(1),
  lockup_type: LogoLockupTypeSchema,
  usage_context: z.string().min(1),
  minimum_size: z.string().min(1),
  clear_space_rule: z.string().min(1),
  placement_notes: z.string().min(1),
  // Precise enough to seed a future prompt compiler: a description exact
  // enough that regenerating this lockup from scratch stays recognizable.
  generation_reference: z.string().min(1)
});

export const BrandVoiceSchema = z.object({
  tone_attributes: z.array(z.string()).min(1),
  writing_dos: z.array(z.string()).default([]),
  writing_donts: z.array(z.string()).default([])
});

export const ColorRoleSchema = z.object({
  role: z.string().min(1),
  description: z.string().min(1),
  // An indicative anchor value, not the canonical token -- exists only so
  // early contrast validation has something to compute against before
  // design_token_set compiles the real value.
  reference_hex: z
    .string()
    .regex(HEX_COLOR_RE, "reference_hex must be a 6-digit hex color (e.g. '#1a2b4c')")
    .nullish()
});

export const MotionCharacterSchema = z.object({
  pace: z.string().min(1),
  emphasis_moments: z.array(z.string()).min(1),
  // Required, not optional: a brand with a kinetic identity that hasn't
  // answered "what happens under prefers-reduced-motion" has an
  // accessibility gap, not an open question.
  reduced_motion_fallback: z.string().min(1)
});

export const BrandCoreSchema = z
  .object({
    brand_name: z.string().min(1),
    positioning_essence: z.string().min(1),
    voice: BrandVoiceSchema,
    color_story: z.array(ColorRoleSchema).min(1),
    typography_direction: z.string().min(1),
    imagery_style: z.string().min(1),
    motion: MotionCharacterSchema,
    logo_lockups: z.array(LogoLockupSchema).min(1)
  })
  .refine(
    (brandCore) => {
      const ids = brandCore.logo_lockups.map((lockup) => lockup.lockup_id);
      return new Set(ids).size === ids.length;
    },
    { message: 'logo_lockups contains duplicate lockup_id(s)', path: ['logo_lockups'] }
  )
  .refine(
    (brandCore) => {
      const primaryCount = brandCore.logo_lockups.filter(
        (lockup) => lockup.lockup_type === 'primary'
      ).length;
      return primaryCount === 1;
    },
    { message: 'logo_lockups must contain exactly one primary lockup', path: ['logo_lockups'] }
  )
  .refine(
    (brandCore) => {
      const swatches = brandCore.color_story.filter(
        (role): role is typeof role & { reference_hex: string } =>
          role.reference_hex != null
      );
      for (let i = 0; i < swatches.length; i += 1) {
        for (let j = i + 1; j < swatches.length; j += 1) {
          const ratio = contrastRatio(swatches[i].reference_hex, swatches[j].reference_hex);
          if (ratio < MINIMUM_COLOR_STORY_DISTINCTION_RATIO) {
            return false;
          }
        }
      }
      return true;
    },
    {
      message: `color_story roles with reference_hex must be visually distinguishable (at least ${MINIMUM_COLOR_STORY_DISTINCTION_RATIO}:1)`,
      path: ['color_story']
    }
  );

export type LogoLockupType = z.infer<typeof LogoLockupTypeSchema>;
export type LogoLockup = z.infer<typeof LogoLockupSchema>;
export type BrandVoice = z.infer<typeof BrandVoiceSchema>;
export type ColorRole = z.infer<typeof ColorRoleSchema>;
export type MotionCharacter = z.infer<typeof MotionCharacterSchema>;
export type BrandCore = z.infer<typeof BrandCoreSchema>;
