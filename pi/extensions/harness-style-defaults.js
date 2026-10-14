// Keep automatic style instructions opt-in for fresh Pi sessions.
export default function harnessStyleDefaults() {
  process.env.PONYTAIL_DEFAULT_MODE ??= "off";
  process.env.PONYTAIL_QUIET_STARTUP ??= "1";
}
