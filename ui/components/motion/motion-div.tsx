"use client";

import { motion, type HTMLMotionProps } from "framer-motion";

/** Isolated so framer-motion is only loaded when animations are ON. */
export function MotionDiv(props: HTMLMotionProps<"div">) {
  return <motion.div {...props} />;
}
