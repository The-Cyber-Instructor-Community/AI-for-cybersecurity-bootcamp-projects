import{Ja as e,Qa as t,Ra as n,io as r,vr as i,za as a}from"./index.dkY5s53S.js";import{n as o,t as s}from"./IFrameUtil.0n70gnmO.js";var c=r(t(),1),l=i(`iframe`,{target:`ei36xw10`})(({theme:e,disableScrolling:t,width:n,height:r})=>({width:n??`100%`,height:r??`100%`,colorScheme:`normal`,border:`none`,padding:e.spacing.none,margin:e.spacing.none,overflow:t?`hidden`:void 0})),u=`streamlit:iframe:setSize`,d=`25rem`,f=`<script>
(function() {
  var lastW = 0, lastH = 0;
  function sendSize() {
    // Guard against malformed HTML (e.g., <frameset>) or script running before body init
    if (!document.body) return;
    // Use getBoundingClientRect for accurate fractional pixel measurement,
    // then ceil to avoid scrollbars from sub-pixel rounding
    var rect = document.body.getBoundingClientRect();
    var w = Math.ceil(Math.max(
      rect.width,
      document.body.scrollWidth,
      document.body.offsetWidth,
      document.documentElement.scrollWidth,
      document.documentElement.offsetWidth
    ));
    var h = Math.ceil(Math.max(
      rect.height,
      document.body.scrollHeight,
      document.body.offsetHeight,
      document.documentElement.scrollHeight,
      document.documentElement.offsetHeight
    ));
    if (w !== lastW || h !== lastH) {
      lastW = w; lastH = h;
      // Note: postMessage with '*' broadcasts to any origin, but this is safe because:
      // 1. This script only runs inside srcdoc (same-origin, sandboxed)
      // 2. The payload is just dimension integers
      // 3. The frontend receiver validates event.source === iframe.contentWindow
      window.parent.postMessage({type: '${u}', width: w, height: h}, '*');
    }
  }
  // Send initial size after DOM is ready
  if (document.readyState === 'complete') {
    sendSize();
  } else {
    window.addEventListener('load', sendSize);
  }
  // Re-measure on DOM changes
  if (typeof MutationObserver !== 'undefined') {
    new MutationObserver(sendSize).observe(document.body, {
      childList: true, subtree: true, attributes: true, characterData: true
    });
  }
  // Re-measure on resize and image/font loading
  window.addEventListener('resize', sendSize);
  document.addEventListener('load', sendSize, true);
})();
<\/script>`;function p(e){return e+f}function m(e){return n(e)||e===``?void 0:e}function h({element:t,widthConfig:n,heightConfig:r}){let i=m(t.src),f=a(i)?void 0:m(t.srcdoc),h=(0,c.useRef)(null),[g,_]=(0,c.useState)({width:null,height:null}),v=n?.useContent??!1,y=r?.useContent??!1,b=a(f)&&(v||y),x=b?p(f):f;(0,c.useEffect)(()=>{if(!b)return;let e=e=>{if(e.source&&e.source===h.current?.contentWindow){let t=e.data;if(t?.type===u&&typeof t?.width==`number`&&typeof t?.height==`number`&&Number.isFinite(t.width)&&Number.isFinite(t.height)&&t.width>=0&&t.height>=0){let e=t.width,n=t.height;_(t=>t.width===e&&t.height===n?t:{width:e,height:n})}}};return window.addEventListener(`message`,e),()=>{window.removeEventListener(`message`,e)}},[b]);let S=b&&v&&g.width!==null?`${g.width}px`:void 0,C;return y&&(b&&g.height!==null?C=`${g.height}px`:a(i)&&(C=d)),e(l,{ref:h,className:`stIFrame`,"data-testid":`stIFrame`,allow:s,disableScrolling:!t.scrolling,src:i,srcDoc:x,scrolling:t.scrolling?`auto`:`no`,sandbox:o,title:`st.iframe`,tabIndex:t.tabIndex??void 0,width:S,height:C})}var g=(0,c.memo)(h);export{g as default};