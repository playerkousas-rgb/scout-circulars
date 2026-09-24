#!/usr/bin/env node
// 直連 SCOUT APP STORE 嘅 Supabase（公開 anon key + RLS 只讀），重寫 appstore.json 嘅 snapshot。
// 用法：node tools/fetch_appstore.mjs
// 注意：sandbox 出唔到 supabase.co；你部機（香港網絡）或 GitHub Actions 都得。
// anon key 只可讀（RLS），呢個 script 唔會寫任何嘢。
import { readFileSync, writeFileSync } from 'fs';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const OUT = join(ROOT, 'appstore.json');
const meta = JSON.parse(readFileSync(OUT, 'utf8'));
const { supabase_url: URL, anon_key: KEY } = meta._meta;

async function get(path) {
  const res = await fetch(`${URL}/rest/v1/${path}`, {
    headers: { apikey: KEY, Authorization: `Bearer ${KEY}` },
  });
  if (!res.ok) throw new Error(`${path} → HTTP ${res.status}: ${await res.text()}`);
  return res.json();
}

const [pages, categories, apps] = await Promise.all([
  get('pages?select=*&order=sort_order'),
  get('categories?select=*&order=page,sort_order'),
  get('apps?select=id,name,url,github,description,note,icon,icon_source,category,page,tags,visible,clicks,stars,hearts,featured,sort_order&order=page,sort_order&limit=1000'),
]);

meta._meta.fetched_at = new Date().toISOString().slice(0, 10);
const doc = { _meta: meta._meta, pages, categories, apps };
writeFileSync(OUT, JSON.stringify(doc, null, 2) + '\n');
console.log(`✅ appstore.json 已更新：${pages.length} pages／${categories.length} categories／${apps.length} apps`);
