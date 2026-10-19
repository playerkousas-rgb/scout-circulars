import json, urllib.request
meta=json.load(open('appstore.json','r',encoding='utf-8'))['_meta']
url=meta['supabase_url']; key=meta['anon_key']
req=urllib.request.Request(f"{url}/rest/v1/apps?select=id,name,url,visible,sort_order,created_at,category,page,tags,description&visible=eq.true&order=sort_order&limit=1000", headers={'apikey':key,'Authorization': f'Bearer {key}'})
with urllib.request.urlopen(req,timeout=30) as r:
    apps=json.loads(r.read().decode())
print(f'TOTAL visible=true: {len(apps)}')
for a in apps:
    print(f"- {a['name']} | {a['url']} | cat={a['category']} page={a['page']} sort={a['sort_order']} created={a.get('created_at')}")
req2=urllib.request.Request(f"{url}/rest/v1/apps?select=id,name,visible&limit=1000", headers={'apikey':key,'Authorization': f'Bearer {key}'})
with urllib.request.urlopen(req2,timeout=30) as r2:
    allapps=json.loads(r2.read().decode())
print(f"ALL total: {len(allapps)} visible_true={sum(1 for x in allapps if x['visible'])} hidden={sum(1 for x in allapps if not x['visible'])}")
