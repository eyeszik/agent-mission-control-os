"use client";

// Token-driven Framer Motion primitives. Each one carries its own LazyMotion
// boundary (only the DOM animation features are loaded) and honours the
// user's reduced-motion setting: transforms are dropped, opacity still fades.
import { LazyMotion, MotionConfig, domAnimation, m } from "framer-motion";
import type { ReactNode } from "react";
import { hoverTransition, revealVariants, revealViewport, staggerVariants } from "../../lib/design/motion";

function MotionScope({ children }: { children: ReactNode }) {
  return (
    <LazyMotion features={domAnimation} strict>
      <MotionConfig reducedMotion="user">{children}</MotionConfig>
    </LazyMotion>
  );
}

type BlockProps = { children: ReactNode; className?: string };

/** Fades a block up when it scrolls into view. Never wrap the LCP element or anything above the fold. */
export function Reveal({ children, className }: BlockProps) {
  return (
    <MotionScope>
      <m.div className={className} initial="hidden" whileInView="visible" viewport={revealViewport} variants={revealVariants}>
        {children}
      </m.div>
    </MotionScope>
  );
}

/** Reveals its StaggerItem children in sequence when the group scrolls into view. */
export function Stagger({ children, className }: BlockProps) {
  return (
    <MotionScope>
      <m.div className={className} initial="hidden" whileInView="visible" viewport={revealViewport} variants={staggerVariants}>
        {children}
      </m.div>
    </MotionScope>
  );
}

/** One child of a Stagger group. Must be rendered inside Stagger. */
export function StaggerItem({ children, className }: BlockProps) {
  return (
    <m.div className={className} variants={revealVariants}>
      {children}
    </m.div>
  );
}

/** Lifts a card slightly on hover and settles on press. */
export function HoverLift({ children, className }: BlockProps) {
  return (
    <MotionScope>
      <m.div className={className} whileHover={{ y: -2 }} whileTap={{ y: 0 }} transition={hoverTransition}>
        {children}
      </m.div>
    </MotionScope>
  );
}
