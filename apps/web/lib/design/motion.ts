// Framer Motion takes numbers, not CSS custom properties, so the motion tokens
// from tokens/amc.tokens.json are mirrored here. tests/motion-tokens.test.ts
// fails if these values drift from the token source.
import type { Transition, Variants } from "framer-motion";

export const MOTION = {
  /** semantic.motion.duration.hover, in seconds */
  hover: 0.2,
  /** semantic.motion.duration.reveal, in seconds */
  reveal: 0.48,
  /** semantic.motion.duration.stagger, in seconds */
  stagger: 0.06,
  /** semantic.motion.easing.standard */
  standard: [0.2, 0, 0, 1],
  /** semantic.motion.easing.emphasized */
  emphasized: [0.16, 1, 0.3, 1],
  /** semantic.motion.offset.reveal, in px */
  revealOffset: 16,
} as const;

const revealTransition: Transition = { duration: MOTION.reveal, ease: [...MOTION.emphasized] };

/** Scroll-triggered fade-up. Use below the fold only: the hidden state is server-rendered. */
export const revealVariants: Variants = {
  hidden: { opacity: 0, y: MOTION.revealOffset },
  visible: { opacity: 1, y: 0, transition: revealTransition },
};

/** Container that reveals its StaggerItem children one after another. */
export const staggerVariants: Variants = {
  hidden: {},
  visible: { transition: { staggerChildren: MOTION.stagger } },
};

/** Hover/press feedback for interactive surfaces. Keyboard focus keeps its own ring. */
export const hoverTransition: Transition = { duration: MOTION.hover, ease: [...MOTION.standard] };

/** Viewport trigger shared by every reveal: once, when a fifth of the element is visible. */
export const revealViewport = { once: true, amount: 0.2 } as const;
