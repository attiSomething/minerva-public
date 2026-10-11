// node tools/render_svg.js <svg> <size> <out.png> [...]: renders SVGs at exact pixel sizes with Playwright's Chromium
const { chromium } = require(process.env.PW || 'playwright');
const fs = require('fs');
(async () => {
  const b = await chromium.launch({ executablePath: process.env.CHROMIUM || undefined });
  const args = process.argv.slice(2);
  for (let i = 0; i < args.length; i += 3) {
    const [svg, size, out] = [args[i], Number(args[i + 1]), args[i + 2]];
    const p = await b.newPage({ viewport: { width: size, height: size } });
    const data = fs.readFileSync(svg, 'utf8');
    await p.setContent(`<html><body style="margin:0;background:transparent"><img style="width:${size}px;height:${size}px;display:block" src="data:image/svg+xml;base64,${Buffer.from(data).toString('base64')}"></body></html>`);
    await p.waitForTimeout(100);
    await p.screenshot({ path: out, omitBackground: true, clip: { x: 0, y: 0, width: size, height: size } });
    await p.close();
  }
  await b.close();
})();
