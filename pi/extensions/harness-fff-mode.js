// Keep the target's FFF defaults portable; explicit process configuration still wins.
export default function harnessFffMode() {
  process.env.PI_FFF_MODE ??= "override";
  process.env.FFF_ENABLE_HOME_SCAN ??= "0";
}
