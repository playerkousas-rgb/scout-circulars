#!/usr/bin/env node
// 將 icons/awards/src/ 入面嘅「童軍總會四支部最高獎章」原圖正規化成 AVIF：
//   icons/awards/<slug>-256.avif（卡片／Story 用）＋ <slug>-64.avif（列表/favicon 用）
// 幾何同 build_org_avif.mjs 一致：contain 入 232px，置中放上 256×256 透明底板，保留 alpha。
// 同時輸出 icons/awards/awards.json（支部 → 獎章／圖示對照表）。
//
// 四個支部最高獎章（來源：香港童軍總會獎章列表／灣仔區童軍會獎勵頁）：
//   幼童軍   → 金紫荊獎章   (Golden Bauhinia Award)
//   童軍     → 總領袖獎章   (Chief Scout's Award)
//   深資童軍 → 榮譽童軍獎章 (Dragon Scout Award)
//   樂行童軍 → 貝登堡獎章   (Baden-Powell Award)
//
// 用法：npm install sharp（本機 scratch 或者 Actions），再
//   NODE_PATH=<sharp 所在>/node_modules node tools/build_award_avif.mjs
import { readFileSync, writeFileSync, readdirSync, mkdirSync } from 'fs';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';
// 允許 sharp 裝喺 repo 外（本機 /tmp scratch）或 repo 內（Actions）
const sharp = (await import('sharp')).default;

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const AWARDS_DIR = join(ROOT, 'icons', 'awards');
const SRC_DIR = join(AWARDS_DIR, 'src');

const AWARDS = [
  { slug: 'cub_gba',   branch: '幼童軍',   zh: '金紫荊獎章',   en: 'Golden Bauhinia Award' },
  { slug: 'scout_csa', branch: '童軍',     zh: '總領袖獎章',   en: "Chief Scout's Award" },
  { slug: 'vs_dsa',    branch: '深資童軍', zh: '榮譽童軍獎章', en: 'Dragon Scout Award' },
  { slug: 'rover_bpa', branch: '樂行童軍', zh: '貝登堡獎章',   en: 'Baden-Powell Award' },
];

mkdirSync(AWARDS_DIR, { recursive: true });

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
const out = { version: 1, generated_at: new Date().toISOString(), awards: {} };
let made = 0;

for (const award of AWARDS) {
  const hit = files.find((f) => f.startsWith(award.slug + '-'));
  if (!hit) {
    console.error(`❌ ${award.branch}（${award.zh}）：icons/awards/src/ 搵唔到 ${award.slug}-* 原圖`);
    continue;
  }
  const srcPath = join(SRC_DIR, hit);
  const buf256 = await normalizeOne(srcPath, 256, 232, 50);
  const buf64 = await normalizeOne(srcPath, 64, 60, 45);
  writeFileSync(join(AWARDS_DIR, `${award.slug}-256.avif`), buf256);
  writeFileSync(join(AWARDS_DIR, `${award.slug}-64.avif`), buf64);
  // PNG 版：Pillow 出 Story 草稿嗰陣食（AVIF 係俾瀏覽器嘅，Pillow 淨係食 PNG）
  const png = await sharp(buf256).png().toBuffer();
  writeFileSync(join(AWARDS_DIR, `${award.slug}-256.png`), png);
  out.awards[award.branch] = {
    slug: award.slug,
    award_zh: award.zh,
    award_en: award.en,
    icon256: `icons/awards/${award.slug}-256.avif`,
    icon64: `icons/awards/${award.slug}-64.avif`,
  };
  made++;
  console.log(`✅ ${award.branch} ${award.zh} → ${award.slug}-256.avif (${(buf256.length / 1024).toFixed(1)}KB)`);
}

writeFileSync(join(AWARDS_DIR, 'awards.json'), JSON.stringify(out, null, 2) + '\n');
console.log(`\n${made}/${AWARDS.length} 個完成正規化；awards.json 已更新`);
process.exit(made === AWARDS.length ? 0 : 2);
