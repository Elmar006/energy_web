/** A brand illustration, never a map or a representation of scenario data. */
export default function NetworkFigure() {
  return (
    <svg className="network-figure" viewBox="0 0 440 360" fill="none" aria-hidden="true">
      <g className="network-blocks">
        <path d="M40 60h88v58H40zM160 24h64v72h-64zM284 48h108v72H284zM28 208h72v108H28zM316 216h96v100h-96zM140 272h108v60H140z" />
        <path d="M40 60l88 58M160 24l64 72M284 48l108 72M28 208l72 108M316 216l96 100M140 272l108 60" />
      </g>
      <path className="network-roads" d="M0 154h116c16 0 28 12 28 28v36c0 16 12 28 28 28h120c16 0 28-12 28-28V0M0 336h116c16 0 28-12 28-28v-62M224 0v128c0 16 12 28 28 28h188M100 0v100M320 246v114" strokeLinecap="round" strokeLinejoin="round" />
      <path className="network-route" d="M40 154h76c16 0 28 12 28 28v36c0 16 12 28 28 28h120c16 0 28-12 28-28v-62" strokeLinecap="round" />
      <g className="network-nodes"><circle cx="40" cy="154" r="7" /><circle cx="144" cy="246" r="7" /><circle cx="320" cy="156" r="7" /></g>
      <circle className="network-halo" cx="228" cy="246" r="52" />
      <circle className="network-hub" cx="228" cy="246" r="30" />
      <path className="network-bolt" d="m232 225-17 25h12l-3 18 18-26h-13l3-17Z" />
      <path className="network-direction" d="m185 241 5 5-5 5m135-58-5 5 5-5 5 5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
