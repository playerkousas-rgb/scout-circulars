#!/usr/bin/env node
// 測試用一次性寫入：將 SCOUT APP STORE 入面 4 本「進度紀錄冊」apps 行嘅 icon
// 換成總會支部最高獎章 AVIF（icons/awards/，raw.githubusercontent 承載）。
//
// 權限（二選一，環境變數）：
//   STORE_SERVICE_KEY                    ← Supabase service_role key（Dashboard → Project Settings → API）
//   STORE_ADMIN_EMAIL + STORE_ADMIN_PASSWORD ← 走網站原有 auth 路由（同 api/admin-login 一樣）
//
// 用法：
//   STORE_SERVICE_KEY=xxx node tools/update_store_award_icons.mjs
// 或 Actions：.github/workflows/update-store-icons.yml（workflow_dispatch）
//
// 未來方向（見 APPSTORE_INTEGRATION.md）：circulars 反過來食 store 嘅 apps.icon，
// 呢個 script 就功成身退。
import { readFileSync } from 'fs';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const store = JSON.parse(readFileSync(join(ROOT, 'appstore.json'), 'utf8'));
const awards = JSON.parse(readFileSync(join(ROOT, 'icons', 'awards', 'awards.json'), 'utf8'));

const URL0 = store._meta.supabase_url;
const ANON = store._meta.anon_key;
const ICON_BASE = process.env.ICON_BASE ||
  'https://raw.githubusercontent.com/playerkousas-rgb/scout-circulars/main';

// 四個進度追蹤工具 → 獎章 slug（同 index.html items 一致）
const TARGETS = [
  { url: 'https://cubsbadge.vercel.app/',  slug: 'cub_gba' },
  { url: 'https://scoutbadge.vercel.app/', slug: 'scout_csa' },
  { url: 'https://vsbadge.vercel.app/',    slug: 'vs_dsa' },
  { url: 'https://roverbadge.vercel.app/', slug: 'rover_bpa' },
];

async function bearerToken() {
  if (process.env.STORE_SERVICE_KEY) return process.env.STORE_SERVICE_KEY;
  const email = process.env.STORE_ADMIN_EMAIL;
  const password = process.env.STORE_ADMIN_PASSWORD;
  if (!email || !password) throw new Error('要 STORE_SERVICE_KEY，或 STORE_ADMIN_EMAIL＋STORE_ADMIN_PASSWORD');
  const res = await fetch(`${URL0}/auth/v1/token?grant_type=password`, {
    method: 'POST',
    headers: { apikey: ANON, 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) throw new Error(`admin 登入失敗 HTTP ${res.status}: ${await res.text()}`);
  return (await res.json()).access_token;
}

const token = await bearerToken();

let ok = 0;
for (const t of TARGETS) {
  const row = store.apps.find((a) => a.url === t.url);
  if (!row) { console.error(`❌ store 搵唔到 ${t.url}`); continue; }
  const icon = `${ICON_BASE}/icons/awards/${t.slug}-256.avif`;
  const res = await fetch(`${URL0}/rest/v1/apps?id=eq.${row.id}`, {
    method: 'PATCH',
    headers: {
      apikey: ANON,
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
      Prefer: 'return=representation',
    },
    body: JSON.stringify({ icon, icon_source: 'upload' }),
  });
  const body = await res.text();
  if (!res.ok) { console.error(`❌ ${row.name}: HTTP ${res.status} ${body}`); continue; }
  ok++;
  console.log(`✅ ${row.name} → ${icon}`);
}
console.log(`\n${ok}/${TARGETS.length} 個 store icon 已更新`);
process.exit(ok === TARGETS.length ? 0 : 2);
