// Keep the target's FFF default portable; explicit process configuration still wins.
export default function harnessFffMode() {
  process.env.PI_FFF_MODE ??= "override";
}
