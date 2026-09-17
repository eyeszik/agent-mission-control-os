import { z } from 'zod';

// Mirrors services/langgraph/agency/artifacts/brand.py. brand_core is the
// canonical brand object every rendering derives from; color and typography
// are described qualitatively here, not as literal tokens -- design_token_set
// compiles this into implementable values downstream.

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
  description: z.string().min(1)
});

export const BrandCoreSchema = z
  .object({
    brand_name: z.string().min(1),
    positioning_essence: z.string().min(1),
    voice: BrandVoiceSchema,
    color_story: z.array(ColorRoleSchema).min(1),
    typography_direction: z.string().min(1),
    imagery_style: z.string().min(1),
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
  );

export type LogoLockupType = z.infer<typeof LogoLockupTypeSchema>;
export type LogoLockup = z.infer<typeof LogoLockupSchema>;
export type BrandVoice = z.infer<typeof BrandVoiceSchema>;
export type ColorRole = z.infer<typeof ColorRoleSchema>;
export type BrandCore = z.infer<typeof BrandCoreSchema>;
