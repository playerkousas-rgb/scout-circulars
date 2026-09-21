#!/usr/bin/env node
// 將 icons/orgs/src/ 入面嘅徽號原圖正規化成 AVIF favicon：
//   icons/orgs/<slug>-256.avif（Story 用）＋ <slug>-64.avif（列表/favicon 用）
// 黑白名單幾何：contain 入 232px，置中放上 256×256 透明底板，保留 alpha。
// 同時輸出 icons/orgs/orgs.json（前端/Story renderer 嘅對照表）：
//   中文名 → { slug, region, status, icon256, icon64 }，未 harvest 嘅標
//   status:"pending-official"＋fallback 去地域或總會徽。
//
// 用法：npm install sharp（本機 scratch 或者 Actions），再
//   node tools/build_org_avif.mjs
import { readFileSync, writeFileSync, readdirSync, mkdirSync, existsSync } from 'fs';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';
import sharp from 'sharp';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const ORGS_DIR = join(ROOT, 'icons', 'orgs');
const SRC_DIR = join(ORGS_DIR, 'src');
const spec = JSON.parse(readFileSync(join(ORGS_DIR, 'official_urls.json'), 'utf8'));
const base = spec._meta.badge_base;

mkdirSync(ORGS_DIR, { recursive: true });

// 地域冇真徽之前，順序跌返：區 → 佢嘅地域 → 總會
const regionSlugFallbackChain = {};

async function normalizeOne(srcPath, size, inner, quality) {
  const img = sharp(srcPath, { animated: false });
  const resized = await img
    .resize(inner, inner, { fit: 'inside', withoutEnlargement: false })
    .toBuffer();
  return sharp({
    create: { width: size, height: size, channels: 4, background: { r: 0, g: 0, b: 0, alpha: 0 } },
  })
    .composite([{ input: resized, gravity: 'center' }])
    .avif({ quality, effort: 4 })
    .toBuffer();
}

const files = readdirSync(SRC_DIR);
const out = { version: 1, generated_at: new Date().toISOString(), fallback: 'sahk', orgs: {} };
let made = 0;

for (const org of spec.orgs) {
  const hit = files.find((f) => f.startsWith(org.slug + '-'));
  if (!hit) {
    regionSlugFallbackChain[org.slug] = org.region === org.name ? 'sahk' : null; // 地域級 fallback 係總會
    out.orgs[org.name] = {
      slug: org.slug, region: org.region, status: 'pending-official',
      icon256: null, icon64: null, badge_source: org.badge_url ? base + org.badge_url : null,
    };
    continue;
  }
  const srcPath = join(SRC_DIR, hit);
  const buf256 = await normalizeOne(srcPath, 256, 232, 50);
  const buf64 = await normalizeOne(srcPath, 64, 60, 45);
  const p256 = join(ORGS_DIR, `${org.slug}-256.avif`);
  const p64 = join(ORGS_DIR, `${org.slug}-64.avif`);
  writeFileSync(p256, buf256);
  writeFileSync(p64, buf64);
  // PNG 版：Pillow 出 Story 草稿嗰陣食（AVIF 係俾瀏覽器嘅，Pillow 淨係食 PNG）
  const png = await sharp(buf256).png().toBuffer();
  writeFileSync(join(ORGS_DIR, `${org.slug}-256.png`), png);
  out.orgs[org.name] = {
    slug: org.slug, region: org.region, status: 'official',
    icon256: `icons/orgs/${org.slug}-256.avif`, icon64: `icons/orgs/${org.slug}-64.avif`,
    badge_source: org.badge_url ? base + org.badge_url : 'wikipedia-svg-render',
  };
  made++;
  console.log(`✅ ${org.name} → ${org.slug}-256.avif (${(buf256.length / 1024).toFixed(1)}KB)`);
}

// 區級 fallback：未 harvest 嘅區，if 佢地域有徽就用地域，否則總會
for (const org of spec.orgs) {
  const entry = out.orgs[org.name];
  if (entry.status !== 'pending-official') continue;
  const regionEntry = out.orgs[org.region];
  entry.fallback = regionEntry && regionEntry.status === 'official' ? org.region : '總會';
}

writeFileSync(join(ORGS_DIR, 'orgs.json'), JSON.stringify(out, null, 2) + '\n');
console.log(`\n${made}/${spec.orgs.length} 個完成正規化；orgs.json 已更新`);
