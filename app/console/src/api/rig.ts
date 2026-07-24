/** Rig profile — the flags nobody should ever retype (crib-sheet convention). */
export const RIG = {
	followerPort: "/dev/tty.usbmodem5AE60832001",
	leaderPort: "/dev/tty.usbmodem5AE60538411",
	robotId: "arm",
	brightnessBand: { min: 115, max: 131 },
	hfUser: "kris0",
} as const;
