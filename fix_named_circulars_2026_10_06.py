#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一次性補正：2026-10-06 用戶點名嘅 13 條通告（東九龍地域 7 條＋總會 6 條）。

背景（PR #51 之後嘅資料欠帳）
------------------------------
PR #51（2026-10-06 合併）修好咗未來防錯規則——分類以標題為準、表格
「截止日期／費用($)」欄、按金唔當費用、郵寄地址唔當對象——但冇改
cache.json／enrich.json，當日入庫嘅資料仍然欠帳：

  1. 東九龍地域（?wpdmdl= 下載連結）7 條一直冇自己嘅 enrich 紀錄
     （之前「搬字過紙」由總會站抄欄位嘅 entry 已經喺 fix_extraction_2026_10_06.py
     撤回）。今次逐條由 hkscout-ekr.org 自己嘅 PDF 補返。
  2. 總會 4 條要補正：
       26228 獎券主通告：售價 HK$10（PDF：「每張獎券售價為 港幣 10 元正」）
       26239 標準艇訓練班：對象漏咗深資童軍／樂行童軍（根因＝「歡迎各合資格的…
              」嘅「合資格」被當成「資格」label，enrich.py extract_audience
              已加 label_mask_terms=("合資格",) 修正，見 test_enrich.py）
       26241 石籃故事：分類由公布改為活動（PDF 明確係保育體驗活動）
       26242 地質生態導賞員訓練班：對象補上童軍人士（PDF 資格（4））
  3. 總會 26229／26232 只核對（活動／2026-11-30；公布／2027-04-15／領袖），
     現值正確就唔改。

鐵律（用戶 2026-10-06 指示）
---------------------------
  - 東九龍地域與總會各自按各自 PDF 抽取；唔可以跨來源複製欄位，唔用 derived_from。
  - 只處理今日點名嘅 13 條；唔跑全量 --backfill，唔掂其他歷史通告。
  - 對照官方來源之後先寫入 enrich.json。

點樣保證「對照官方來源後才寫入」
-------------------------------
  下面每條通告都有 PDF 文字層常量（2026-10-06 由官方 URL 逐份攞返嚟：
  東九龍地域 = hkscout-ekr.org/circulars/download/?wpdmdl=…、
  總會 = scout.org.hk/uploads/tc/circulars/…，各自分別核實）。本 script 用
  enrich.py 自己嘅 extract_fields()（分類／截止／對象／費用／訂閱標籤）行一次，
  同 EXPECTED（人手逐字核對官方 PDF 嘅值）比對——**任何一欄唔啱都會即刻
  中止，一個字都唔寫**；全部通過先寫入 enrich.json。

  表格常量（5653／5655 兩份日期表）係 PDF 表格重排（pdfplumber
  extract_tables() 形狀），「截止日期／費用($)／按金」欄逐格核對過
  （fee_from_tables 只認費用／班費／收費欄名，「按金」欄唔會被當費用）。

  註：26239／26241／26242 係總會站同一份通告（SA69／SA70／SA71.pdf），
  內容同東九龍地域 5653／5654／5655 逐字相同——2026-10-06 已由兩個官方
  URL 分別下載核實。呢度照樣各自跑一次 extract_fields（各自來源、各自
  entry），冇任何欄位由另一個來源複製。

用法
----
    python fix_named_circulars_2026_10_06.py --dry-run   # 只睇會改咩
    python fix_named_circulars_2026_10_06.py             # 實際寫入 enrich.json

（可重複執行：第二次 run 會顯示「已經乾淨」。零下載、唔改 cache.json
 ——列表標題本來就正確，category 只住喺 enrich.json。）
"""
from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from enrich import (  # noqa: E402
    ENRICH_VERSION, HKT, extract_fields, normalize_fee, reconcile_listing_title,
)

BASE_DIR = Path(__file__).parent
CACHE_PATH = BASE_DIR / "cache.json"
ENRICH_PATH = BASE_DIR / "enrich.json"

EKR_BASE = "https://hkscout-ekr.org/circulars/download/?wpdmdl="
HQ_BASE = "https://scout.org.hk/uploads/tc/circulars"

# ══════════════════════════════════════════════════════════════════════
# 東九龍地域：7 條 PDF 文字層（各自官方 URL，2026-10-06 核實）
# ══════════════════════════════════════════════════════════════════════

# 5653 https://hkscout-ekr.org/circulars/download/?wpdmdl=5653
# 證據：表格「費用($)」=160、「截止日期」=2026年12月11日；
#       （二）參加資格：（1）…之童軍、深資童軍及樂行童軍成員；或…之各級領袖
EKR_5653_TEXT = """三級童軍標準艇訓練班
Level 3 Scout Standard Boat Course
地域將於 2027 年 1 月在白沙灣譚華正海上活動中心舉辦上述訓練班，由香港童軍總會註冊中級童軍標準艇教練員楊劍聰先生擔任班領導人，歡迎各合資格的童軍成員及領袖踴躍參加。本訓練班獲「青少年成員及童軍領袖訓練資助計劃」資助，合資格者之班費因此獲得減半，詳情如下：
（一）日期：
日期 星期 時間 費用($) 名額 截止日期
2027年1月2日 六 0900至1700 160 14 2026年12月11日
2027年1月3日 日 0900至1700 160 14 2026年12月11日
2027年1月9日 六 0900至1700 160 14 2026年12月11日
2027年1月10日 日 0900至1700 160 14 2026年12月11日
2027年1月16至17日 六至日 海上旅程 160 14 2026年12月11日
2027年1月24日 (後備日) 日 待定 160 14 2026年12月11日
（二）參加資格：（1）持有有效童軍紀錄冊及童軍成員編號之童軍、深資童軍及樂行童軍成員；
或持有有效領袖委任書或教練員委任證之各級領袖；
（2）持有有效游泳測試證明書（未持有者可向各地域查詢有關游泳測試安排）；及
（3）持有二級童軍標準艇證書或已考獲水手章。
（4）18 歲以下之參加者必須簽署家長／監護人同意書（RT06）。
（5）本地域轄下支部成員／領袖將獲優先考慮。
（三）參加辦法：報名表格（RT04）及家長／監護人同意書（RT06）【只適用於 18 歲以下之參加者】可於東九龍地域總部及白沙灣譚華正海上活動中心索取，或於下列網站下載：https://hkscout-ekr.org。
填妥表格後經由有關領袖副署並加蓋旅印，連同費用*、游泳測試證明書副本及相關資歷副本，於截止日期前寄／交回新界西貢白沙灣西貢公路 600 號，香港童軍總會白沙灣譚華正海上活動中心收。
*參加費用包括行政費、講義及證書，支票抬頭請書「香港童軍總會白沙灣譚華正海上活動中心」為收款人，一人一票。
（四）其他：（1）凡逾期遞交報名表格、未附家長／監護人同意書（如適用）、未附有關證書／證明副本、未經有關領袖副署及加蓋旅印，或未繳交費用者，概不接納申請。
（2）申請一經接納，參加資格不可轉讓別人。
（3）參加者必須全期出席，不得遲到或早退。
（4）帶備游泳測試證明書正本出席。
（5）自備水樽、午餐及活動衣物（包踭包趾鞋及游泳衣物等）。
（6）完成訓練班及經考試合格者，將獲發三級童軍標準艇證書。
（7）考獲本訓練班證書等同完成「童軍／深資童軍支部海上活動徽章—水手長章」的要求。
（8）參加者可選擇自費購買童軍標準艇紀錄冊。
（9）取錄與否，由班領導人決定，一概以電郵通知，參加者不得異議。
（10）有經濟需要之青少年成員／童軍領袖可分別根據「學生隊員訓練資助計劃（由民政及青年事務局資助）」／「有經濟需要之童軍領袖訓練資助計劃」申請全額資助參加本訓練班，詳情請參閱相關通告。
（11）本訓練班／活動之相片將存放於香港童軍總會，有機會用作訓練班／活動宣傳之用。如參加者不同意有關拍攝事宜，請將個人意願連同姓名、訓練班／活動名稱及日期電郵至 psw@scout.org.hk。
（12）參加者如在班期前一星期尚未收到通知，請於辦公時間致電 2719 8979 與中心職員施中傑先生聯絡。
副地域總監（活動與訓練）
（楊劍聰代行）
"""

# 5653 PDF 表格（日期表：費用($)=160／截止日期=2026年12月11日）
EKR_5653_TABLES = [[
    ["日期", "星期", "時間", "費用($)", "名額", "截止日期"],
    ["2027年1月2日", "六", "0900至1700", "160", "14", "2026年12月11日"],
    ["2027年1月3日", "日", "0900至1700", "160", "14", "2026年12月11日"],
    ["2027年1月9日", "六", "0900至1700", "160", "14", "2026年12月11日"],
    ["2027年1月10日", "日", "0900至1700", "160", "14", "2026年12月11日"],
    ["2027年1月16至17日", "六至日", "海上旅程", "160", "14", "2026年12月11日"],
    ["2027年1月24日 (後備日)", "日", "待定", "160", "14", "2026年12月11日"],
]]

# 5651 https://hkscout-ekr.org/circulars/download/?wpdmdl=5651
# 證據：【請於 2026 年 11 月 30 日（星期一）前回覆】；
#       「致：東九龍地域總部辦事處九龍柯士甸道童軍徑香港童軍中心 9 樓 923 室」
#       係郵寄地址——唔可以抽成參加對象（enrich.py _recipient_scope 地址特徵把關）
EKR_5651_TEXT = """香港童軍總會東九龍地域 2027 年童軍獎券籌募活動
回 條
【請於 2026 年 11 月 30 日（星期一）前回覆】
致 ：東九龍地域總部辦事處九龍柯士甸道童軍徑香港童軍中心 9 樓 923 室
傳真︰2302 1168
電郵：ekr@scout.org.hk
東九龍 區 第 旅
□ 將參與 2027 年童軍獎券籌募活動，請分配 張獎券。
（以每百為單位）
□ 不會參與 2027 年童軍獎券籌募活動。
旅 印：
旅長／負責領袖簽署：
聯絡電話：
姓 名：
（請以正楷填寫）
電郵地址（必須填寫）：
日 期：
備註：
（1）請在適當空格內填上「✓」號。
（2）本表格內填報的個人及其他有關資料，只供本地域處理是次申請有關用途。在表格內提供的個人及其他有關資料純屬自願。然而，如果沒有正確或足夠的資料，本地域可能無法處理有關申請。在一般情況下，本表格將於活動完成後 6 個月銷毀。
"""

# 5650 https://hkscout-ekr.org/circulars/download/?wpdmdl=5650
# 證據：「每張獎券售價為 港幣 10 元正」→ HK$10；
#       「必須於 2026 年 11 月 30 日（星期一）或之前填妥夾附回條」→ 2026-11-30
EKR_5650_TEXT = """香港童軍總會 東九龍地域 行政通告第25/2026號
電話：2957 6466 傳真：2302 1168 2026年10月1日
2027年童軍獎券籌募活動 Scout Raffle Campaign 2027
2027 年童軍獎券籌募活動將於 2027 年 1 月 17 日（星期日）至 3 月 5 日（星期五）期間舉行，每張獎券售價為 港幣 10 元正， 童軍旅收益之分賬為實際銷售額之 65%。根據獎券活動牌照條件規定，獎券不能在上述銷售日期以外銷售， 及不得於任何政府管理或擁有的道路、街道、行人路、行人天橋、小路、小巷、小徑、廣場或球場售賣或兜售，亦不得在其他公共地方售賣或兜售， 敬請各銷售的童軍單位／成員嚴格遵守獎券活動牌照的條件。如任何人士在未經許可下，在公共地方售賣或兜售獎券，便屬違法，而本會則可能遭牌照事務處撤銷獎券活動牌照。
參與獎券銷售活動之童軍旅必須呈交 2025／2026 年度賬目結算表予所屬區總監審核，及在上年度獎券籌募活動中， 準時交回券款及未銷售之獎券，始獲准許分發獎券。而在 2025 年 6 月 1 日或以後成立（即開辦仍未滿 18 個月）的童軍旅則可獲豁免上述之規定。
為統計領取獎券數量，各旅長／負責領袖必須於 2026 年 11 月 30 日（星期一）或之前 填妥夾附回條，交回東九龍地域總部辦事處。逾期未交回條之童軍旅，將當作不參與 2027 年童軍獎券籌募活動。
為鼓勵童軍旅積極參與，2027 年童軍獎券籌募活動繼續設銷售獎及進步獎，所有獎項將於 2027 年 3 月 13 日舉行的童軍獎券抽獎典禮頒發，有意參與獎券銷售獎勵比賽的童軍旅請留意總會稍後發出之獎券籌募通告。
如有查詢，請於辦公時間與訓練幹事陳嘉寳小姐（電話：2957 6465）或二級文員郭麗民小姐（電話︰2957 6460）聯絡。
地域總監
（梁偉倫 代行）
"""

# 5646 https://hkscout-ekr.org/circulars/download/?wpdmdl=5646
# 證據：（四）截止日期：2027 年 4 月 15 日（星期四）；
#       （二）參加資格：（1）現役各級旅團領袖（包括教練員）→ 領袖；
#       標題「嘉許計劃」＝公布
EKR_5646_TEXT = """卓越領袖嘉許計劃 2027
為鼓勵前線領袖積極推動童軍運動，啟發青少年成員的發展和引領他們成長，並參與區、地域以至總會的活動與訓練，地域推出上述計劃，藉以表揚有卓越表現的旅團領袖。詳情如下：
（一）評審準則：前線領袖在 2026 年 4 月 1 日至 2027 年 3 月 31 日（「評審期」）期間在童軍旅的服務記錄及童軍其他方面的參與和表現。
（二）參加資格：符合以下（1）至（5）項：
（1）現役各級旅團領袖（包括教練員）；
從未獲總會功績榮譽奬勵，即優良服務或以上獎章。
（2）在評審期內或之前在所屬旅團服務已滿 1 年或以上。
（3）在評審期內完成以下各項：
（a）不少於 10 次帶領旅團集會或其他活動；
（b）不少於 2 次出席所屬童軍區舉行的會議；
（c）不少於 4 次帶領旅團成員參與所屬童軍區、地域或總會的活動、服務或事工；及
（d）不少於 1 次以旅團領袖身分協助所屬童軍區、地域或總會的活動、服務或事工。
（4）在評審期內完成不少於 1 個領袖木章或技能訓練班。
（5）出席於 2027 年 6 月舉行的面談，並在面談中分享上述(2)至(4)項的參與。
（三）參加辦法：經區總監／旅長提名或自薦參加，於截止日期或之前填妥網上表格提交基本資料，其後按通知於指定日期前補充詳細資料。遞交前請確保資料正確無誤，以免影響參加資格。
（四）截止日期：2027 年 4 月 15 日（星期四）
（五）嘉許方式：經評審而獲嘉許之領袖，將獲頒發地域總監嘉許狀，以資表揚。
（六）備註：（1）請參閱附錄有關本計劃之主要日期及安排。
（2）在評審過程中，如有任何特殊情況或爭議，地域將檢視情況及相關考慮，並保留本計劃的最終決定權。
如對本計劃有任何疑問，請與所屬童軍區之區總監或地域執行幹事梁偉倫先生聯絡（電話：2957 6468）。
地域總監
（蔣紹恒 紹華代行）
"""

# 5654 https://hkscout-ekr.org/circulars/download/?wpdmdl=5654
# 證據：（八）截止日期：2026 年 12 月 18 日（星期五）；（六）費用：全免；
#       （五）參加資格：（1）幼童軍、童軍、深資童軍及樂行童軍支部成員
#       （2）各級領袖（3）會務委員（4）親友（5）各界人士
#       ——對象按呢份 PDF 抽（支部主體 6 個；親友／各界唔係支部標籤）
EKR_5654_TEXT = """東九龍地域 50 周年暨
賽馬會童「SING」匯航計劃
一個石籃的故事
東九龍地域一直貫徹可持續發展與環境保育的理念，自 2019 年起更與漁農自然護理署合作推動山徑維修工作。適逢地域成立 50 周年，白沙灣譚華正海上活動中心亦獲香港賽馬會慈善信託基金資助，特舉辦「一個石籃的故事」活動，旨在向大眾傳遞保護自然環境的重要訊息，鼓勵參加者通過親身體驗實踐保育行動，為守護自然生態出一分力。
是次活動獲得漁農自然護理署支持，參加者將會在富經驗的導師指導下，認識石籃的應用和編織方法，參與石籃編織，並有機會親自將石籃製成品放置山徑旁，以便減低水土流失而影響郊遊人士安全。活動由助理地域總部總監（專責）林鼎坤先生擔任負責人，歡迎幼童軍或以上支部成員、領袖、會務委員、親友及各界人士踴躍參加，詳情如下：
（一）日期：
編號 活動項目 日期 星期 時間 地點 名額
A 認識石籃的應用和編織方法、編織石籃 2027年1月10日 日 0930至1230 白沙灣譚華正海上活動中心 50
B 放置石籃 2027年1月10日 日 1330至1530 西貢獅子會自然教育中心、蕉坑自然教育徑 50
（二）活動項目：參加者可選擇只參與活動 A，或參與全期活動。
（三）石籃介紹：石籃，是用麻繩編織成網袋，再放入石頭，放置於山徑兩旁水土流失嚴重的位置。在落雨的時候，山水經過石籃後，沙泥會被阻擋及積聚，這樣能減低水土流失而導致山徑崩塌，從而減低郊遊人士受傷的機會。
（四）內容：在富經驗導師的指導下：
（1）認識石籃的應用及編織方法；
（2）編織石籃；及
（3）放置石籃。
（五）參加資格：（1）6 歲或以上持有有效紀錄冊之幼童軍、童軍、深資童軍及樂行童軍支部成員；
（2）持有有效領袖委任書或教練員委任證之各級領袖；
（3）持有有效委任狀之會務委員；
（4）以上各合資格童軍人士的 6 歲或以上親友；或
（5）6 歲或以上各界人士。
參加者須注意以下各項：
（1）年齡介乎 6 至 11 歲之參加者必須在家長／監護人或領袖陪同下一起參與活動。
（2）本地域轄下成員及其親友將獲優先考慮。
（3）活動 B 涉及輕度體力工作（請自我衡量體能狀況後才報名參加）。
（六）費用：全免
（七）參加辦法：（1）網上報名：於截止日期前登入 https://forms.gle/q1utXznGzuTVQ6qe7 報名；或
（2）郵寄報名：填妥「賽馬會童『SING』匯航計劃」報名表格【表格可於東九龍地域總部及白沙灣譚華正海上活動中心索取，或於下列網站下載：http://hkscout-ekr.org】，於截止日期或以前寄／交回新界西貢白沙灣西貢公路 600 號，香港童軍總會白沙灣譚華正海上活動中心收。
（八）截止日期：2026 年 12 月 18 日（星期五）
（九）其他：（1）凡逾期遞交報名表格，概不接受報名。
（2）申請一經接納，參加資格不可轉讓別人。
（3）參加者必須全期出席，不得遲到或早退，方獲發出席證書。
（4）參加者須自備糧水。
（5）取錄與否，由活動負責人決定，一概以電郵通知，參加者不得異議。
（6）活動 A 完結後參加者需步行前往西貢獅子會自然教育中心進行活動 B。
（7）本活動之相片將存放於香港童軍總會，有機會用作活動或宣傳之用。如參加者不同意有關拍攝事宜，請將個人意願連同姓名、活動名稱及日期電郵至 psw@scout.org.hk。
（8）參加者如在活動前一星期尚未收到通知，請於辦公時間致電 2719 8979 與中心職員施中傑先生聯絡。
副地域總監（活動與訓練）
（林鼎坤代行）
"""

# 5655 https://hkscout-ekr.org/circulars/download/?wpdmdl=5655
# 證據：表格「截止日期」=2026年12月19日；「按金」欄=$300——按金可退
#       （（四）（3）「…方獲發出席證書及退回按金」），唔係費用 → fee 留空；
#       （二）參加資格：（1）各級領袖（2）會務委員（3）各界人士
#       （4）童軍人士必須持有有效游泳測試證明書 → 對象含童軍人士（支部＝童軍）
EKR_5655_TEXT = """賽馬會童「SING」匯航計劃
地質生態導賞員訓練班
Jockey Club Scout "S.I.N.G" Programme Geo Tour Guide Training Course
生態及地質旅遊在香港日漸普及，白沙灣譚華正海上活動中心獲香港賽馬會慈善信託基金撥款資助以舉辦上述訓練，向對自然生態及環境保育有興趣之人士教授生態及地質知識，以便日後協助帶領導賞活動，宣揚環境保育訊息。本訓練班由獲推薦地質公園導賞員（地質公園導賞員推薦制度）陳琚瑋女士負責，歡迎領袖、會務委員及各界人士踴躍參加，詳情如下：
（一）日期：
日期 星期 地點 堂數 時間 按金 名額 截止日期
2027年1月13日 三 香港童軍中心 5 1900-2200 $300 10 2026年12月19日
2027年1月17日 日 白沙灣 5 0900-1700 $300 10 2026年12月19日
2027年1月20日 三 香港童軍中心 5 1900-2200 $300 10 2026年12月19日
2027年1月23日 六 白沙灣 5 0900-1700 $300 10 2026年12月19日
2027年1月31日 日 西貢地質公園 5 0900-1700 $300 10 2026年12月19日
（二）參加資格：
（1）持有有效領袖委任書或教練員委任證之各級領袖；
（2）持有有效委任證之會務委員；或
（3）各界人士。
（4）童軍人士必須持有有效游泳測試證明書（未持有者可向各地域查詢有關游泳測試安排）。
（5）持有獨木舟教練資歷、遊樂船隻二級操作人證書或同等資歷將獲優先考慮。
（6）本地域轄下成員將獲優先考慮。
（三）參加辦法：
「賽馬會童『SING』匯航計劃」報名表格可於東九龍地域總部及白沙灣譚華正海上活動中心索取，或於下列網站下載：http://www.hkscoutekr.org。
填妥報名表格後連同按金*、游泳測試證明書及有關證書副本，於截止日期或以前寄／交回新界西貢白沙灣西貢公路 600 號，香港童軍總會白沙灣譚華正海上活動中心收。
*支票抬頭請書「香港童軍總會白沙灣譚華正海上活動中心」為收款人，一人一票。
（四）其他：（1）凡逾期遞交報名表格、未附有關證書／證明副本，或未繳交按金者，概不接納申請。
（2）申請一經接納，參加資格不可轉讓別人。
（3）參加者必須全期出席，不得遲到或早退，並完成額外 3 日實習課節，方獲發出席證書及退回按金。
（4）帶備游泳測試證明書（Certificate of Swimming Test）出席訓練班。
（5）自備糧水及活動衣物（布鞋及游泳衣物等）。
（6）取錄與否，由班領導人決定，一概以電郵通知，參加者不得異議。
（7）本活動之相片將存放於香港童軍總會，有機會用作活動或宣傳之用。如參加者不同意有關拍攝事宜，請將個人意願連同姓名、活動名稱及日期電郵至 psw@scout.org.hk
（8）參加者如在班期前一星期尚未收到通知，請於辦公時間致電 2719 8979 與中心職員郭美宝小姐聯絡。
副地域總監（活動與訓練）
（鄧適烈代行）
"""

# 5655 PDF 表格（「按金」欄 $300 可退 → fee_from_tables 只認費用／班費／收費欄名，
# 唔會攞按金；截止日期欄＝2026年12月19日）
EKR_5655_TABLES = [[
    ["日期", "星期", "地點", "堂數", "時間", "按金", "名額", "截止日期"],
    ["2027年1月13日", "三", "香港童軍中心", "5", "1900-2200", "$300", "10", "2026年12月19日"],
    ["2027年1月17日", "日", "白沙灣", "5", "0900-1700", "$300", "10", "2026年12月19日"],
    ["2027年1月20日", "三", "香港童軍中心", "5", "1900-2200", "$300", "10", "2026年12月19日"],
    ["2027年1月23日", "六", "白沙灣", "5", "0900-1700", "$300", "10", "2026年12月19日"],
    ["2027年1月31日", "日", "西貢地質公園", "5", "0900-1700", "$300", "10", "2026年12月19日"],
]]

# 5649 https://hkscout-ekr.org/circulars/download/?wpdmdl=5649
# 證據：賽果通告（步操／團呼／快樂傘比賽冠亞季軍名單）——「成績公布」係比賽類；
#       冇截止日／費用／對象欄位
EKR_5649_TEXT = """東九龍地域步操、團呼及快樂傘比賽 2026
East Kowloon Regional Footdrill, Grand Howl &Para-Balloon Competition 2026
成績公布
地域步操、團呼及快樂傘比賽 2026 已於本年 9 月 20 日假聖若瑟英文中學順利舉行，有關比賽成績臚列如下：
步操比賽
冠 軍 ： 東九龍第 10 旅
上述獲獎單位將獲地域提名參加 2026 年香港童軍大會操之步操比賽。
團呼比賽
冠 軍： 東九龍第 195 旅
亞 軍： 東九龍第 138 旅
季 軍： 東九龍第 137 旅
優 異 獎： 東九龍第 21 旅
優 異 獎： 東九龍第 1221 旅
最佳亞基拿： 東九龍第 138 旅 梁彥喬
快樂傘比賽
冠 軍： 東九龍第 1324 旅
亞 軍： 東九龍第 1499 旅
季 軍： 東九龍第 1501 旅
優 異 獎 ： 東九龍第 195 旅
地域總監
（鄭藍藍代行）
"""

# 東九龍地域：expected（官方 PDF 逐字核對，2026-10-06）
#   key = wpdmdl ID；title = cache.json 官方列表標題
EKR_EXPECTED = {
    "5653": {
        "title": "三級童軍標準艇訓練班",
        "deadline": "2026-12-11",
        "audience": "深資童軍、樂行童軍、童軍、領袖",
        "fee": "HK$160",
        "category": "訓練",
        "text": EKR_5653_TEXT,
        "tables": EKR_5653_TABLES,
    },
    "5651": {
        "title": "2027年童軍獎券籌募活動 - 回條",
        "deadline": "2026-11-30",
        "audience": "",   # 郵寄地址唔可以抽成參加對象
        "fee": "",
        "category": "活動",
        "text": EKR_5651_TEXT,
        "tables": None,
    },
    "5650": {
        "title": "2027年童軍獎券籌募活動",
        "deadline": "2026-11-30",
        "audience": "",
        "fee": "HK$10",   # 每張獎券售價為港幣10元正
        "category": "活動",
        "text": EKR_5650_TEXT,
        "tables": None,
    },
    "5646": {
        "title": "卓越領袖嘉許計劃2027",
        "deadline": "2027-04-15",
        "audience": "領袖",
        "fee": "",
        "category": "公布",
        "text": EKR_5646_TEXT,
        "tables": None,
    },
    "5654": {
        "title": "東九龍地域50周年暨賽馬會童「SING」匯航計劃 - 一個石籃的故事",
        "deadline": "2026-12-18",
        "audience": "幼童軍、深資童軍、樂行童軍、童軍、領袖、會務委員",
        "fee": "全免",
        "category": "活動",
        "text": EKR_5654_TEXT,
        "tables": None,
    },
    "5655": {
        "title": "東九龍地域50周年暨賽馬會童「SING」匯航計劃 - 地質生態導賞員訓練班",
        "deadline": "2026-12-19",
        "audience": "童軍、領袖、會務委員",
        "fee": "",         # $300 係按金（可退），唔係費用
        "category": "訓練",
        "text": EKR_5655_TEXT,
        "tables": EKR_5655_TABLES,
    },
    "5649": {
        "title": "東九龍地域步操、團呼及快樂傘比賽2026 - 成績公布",
        "deadline": "",
        "audience": "",
        "fee": "",
        "category": "比賽",
        "text": EKR_5649_TEXT,
        "tables": None,
    },
}

# ══════════════════════════════════════════════════════════════════════
# 總會：4 條要補正＋2 條只核對（各自官方 URL，2026-10-06 核實）
# ══════════════════════════════════════════════════════════════════════

# 26228 https://scout.org.hk/uploads/tc/circulars/26228/Adm25.pdf
# 補正：售價 HK$10（「每張獎券售價為 港幣 10 元正」）；活動／2026-11-30 現值已正確
HQ_26228_TEXT = """香港童軍總會 東九龍地域 行政通告第25/2026號
電話：2957 6466 傳真：2302 1168 2026年10月1日
2027年童軍獎券籌募活動 Scout Raffle Campaign 2027
2027 年童軍獎券籌募活動將於 2027 年 1 月 17 日（星期日）至 3 月 5 日（星期五）期間舉行，每張獎券售價為 港幣 10 元正， 童軍旅收益之分賬為實際銷售額之 65%。根據獎券活動牌照條件規定，獎券不能在上述銷售日期以外銷售， 及不得於任何政府管理或擁有的道路、街道、行人路、行人天橋、小路、小巷、小徑、廣場或球場售賣或兜售，亦不得在其他公共地方售賣或兜售， 敬請各銷售的童軍單位／成員嚴格遵守獎券活動牌照的條件。如任何人士在未經許可下，在公共地方售賣或兜售獎券，便屬違法，而本會則可能遭牌照事務處撤銷獎券活動牌照。
參與獎券銷售活動之童軍旅必須呈交 2025／2026 年度賬目結算表予所屬區總監審核，及在上年度獎券籌募活動中， 準時交回券款及未銷售之獎券，始獲准許分發獎券。而在 2025 年 6 月 1 日或以後成立（即開辦仍未滿 18 個月）的童軍旅則可獲豁免上述之規定。
為統計領取獎券數量，各旅長／負責領袖必須於 2026 年 11 月 30 日（星期一）或之前 填妥夾附回條，交回東九龍地域總部辦事處。逾期未交回條之童軍旅，將當作不參與 2027 年童軍獎券籌募活動。
為鼓勵童軍旅積極參與，2027 年童軍獎券籌募活動繼續設銷售獎及進步獎，所有獎項將於 2027 年 3 月 13 日舉行的童軍獎券抽獎典禮頒發，有意參與獎券銷售獎勵比賽的童軍旅請留意總會稍後發出之獎券籌募通告。
如有查詢，請於辦公時間與訓練幹事陳嘉寳小姐（電話：2957 6465）或二級文員郭麗民小姐（電話︰2957 6460）聯絡。
地域總監
（梁偉倫 代行）
"""

# 26239／26241／26242：總會站同一份通告（SA69／SA70／SA71.pdf），
# 文字層同東九龍地域 5653／5654／5655 逐字相同——2026-10-06 已由兩個官方
# URL 分別下載核實。下面照樣各自跑 extract_fields（各自來源、各自 entry）。
HQ_26239_TEXT = EKR_5653_TEXT
HQ_26241_TEXT = EKR_5654_TEXT
HQ_26242_TEXT = EKR_5655_TEXT

# 總會：expected（官方 PDF 逐字核對，2026-10-06）
HQ_FIXES = {
    f"{HQ_BASE}/26228/Adm25.pdf": {
        "title": "2027年童軍獎券籌募活動",
        "deadline": "2026-11-30",
        "audience": "",
        "fee": "HK$10",      # 補正：售價
        "category": "活動",
        "text": HQ_26228_TEXT,
        "tables": None,
        "note": "售價 HK$10（每張獎券售價為港幣10元正）",
    },
    f"{HQ_BASE}/26239/SA69.pdf": {
        "title": "三級童軍標準艇訓練班",
        "deadline": "2026-12-11",
        "audience": "深資童軍、樂行童軍、童軍、領袖",   # 補正：補齊深資／樂行
        "fee": "HK$160",
        "category": "訓練",
        "text": HQ_26239_TEXT,
        "tables": EKR_5653_TABLES,
        "note": "對象補齊（（二）參加資格（1）…童軍、深資童軍及樂行童軍成員；或各級領袖）",
    },
    f"{HQ_BASE}/26241/SA70.pdf": {
        "title": "東九龍地域50周年暨賽馬會童「SING」匯航計劃 - 一個石籃的故事",
        "deadline": "2026-12-18",
        "audience": "幼童軍、深資童軍、樂行童軍、童軍、領袖、會務委員",   # 保留 PDF 完整對象
        "fee": "全免",
        "category": "活動",  # 補正：由公布改為活動
        "text": HQ_26241_TEXT,
        "tables": None,
        "note": "分類公布→活動（PDF：特舉辦「一個石籃的故事」活動）",
    },
    f"{HQ_BASE}/26242/SA71.pdf": {
        "title": "東九龍地域50周年暨賽馬會童「SING」匯航計劃 - 地質生態導賞員訓練班",
        "deadline": "2026-12-19",
        "audience": "童軍、領袖、會務委員",   # 補正：補上童軍人士
        "fee": "",   # $300 係按金（可退），唔可以當費用
        "category": "訓練",
        "text": HQ_26242_TEXT,
        "tables": EKR_5655_TABLES,
        "note": "對象補上童軍人士；按金唔當費用",
    },
}

# 總會：只核對、唔改（用戶：若現值已正確，無須改）
HQ_VERIFY_ONLY = {
    f"{HQ_BASE}/26229/Adm25-app.pdf": {
        "title": "2027年童軍獎券籌募活動 - 回條",
        "deadline": "2026-11-30",
        "category": "活動",
    },
    f"{HQ_BASE}/26232/Adm28.pdf": {
        "title": "卓越領袖嘉許計劃2027",
        "deadline": "2027-04-15",
        "audience": "領袖",
        "category": "公布",
    },
}


def short_id(url):
    """報告用嘅短 ID：EKR 5653／HQ 26228/Adm25。"""
    if "wpdmdl=" in url:
        return "EKR " + url.rsplit("=", 1)[-1]
    tail = url.split("/circulars/")[-1]          # 26228/Adm25.pdf
    return "HQ " + tail.rsplit(".", 1)[0]        # HQ 26228/Adm25


def find_cache_item(cache, url):
    """喺 cache.json（data 分組＋notices 扁平份）搵返通告，攞官方列表標題。"""
    for arr in (cache.get("data") or {}).values():
        if isinstance(arr, list):
            for item in arr:
                if isinstance(item, dict) and (item.get("pdf_url") or item.get("url")) == url:
                    return item
    for item in cache.get("notices") or []:
        if isinstance(item, dict) and (item.get("pdf_url") or item.get("url")) == url:
            return item
    return None


def extract_and_check(url, exp, source, problems):
    """用 enrich.py 自己嘅抽取邏輯行一次，同官方 PDF 核實嘅 expected 逐欄比對。

    任何一欄唔啱 → 記入 problems（caller 會中止、唔寫檔）。
    回傳 extract_fields 結果（全部通過先有用）。
    """
    res = extract_fields(exp["text"], exp["title"], source=source, tables=exp.get("tables"))
    checks = [
        ("截止", res.get("deadline", ""), exp["deadline"]),
        ("對象", res.get("audience", ""), exp["audience"]),
        ("費用", normalize_fee(res.get("fee", "")), exp["fee"]),
        ("分類", "、".join(c.get("label", "") for c in (res.get("categories") or [])), exp["category"]),
    ]
    for field, got, want in checks:
        if got != want:
            problems.append(f"{short_id(url)} {field}：抽到 {got!r}，官方 PDF 核實係 {want!r}")
    return res


def build_entry(source, title, res, title_check):
    """照 enrich.py main() 寫 enrich.json 嘅格式組一條 entry。"""
    return {
        "source": source,
        "title": title,
        "deadline": res.get("deadline", ""),
        "audience": res.get("audience", ""),
        "fee": normalize_fee(res.get("fee", "")),
        "categories": res.get("categories") or [],
        "branch_tags": res.get("branch_tags") or [],
        "subscription_tags": res.get("subscription_tags") or [],
        "subscription_tag_details": res.get("subscription_tag_details") or [],
        "subscription_catalog_version": res.get("subscription_catalog_version", ""),
        "method": "text",
        "error": "",
        "title_check": title_check,
        "enriched_at": datetime.datetime.now(HKT).strftime("%Y-%m-%d %H:%M:%S"),
        "enrich_version": ENRICH_VERSION,
    }


def entry_signature(entry):
    """比對用嘅欄位簽名（唔含 enriched_at——時間戳變咗唔代表資料變咗）。"""
    if not isinstance(entry, dict):
        return None
    keys = ("source", "title", "deadline", "audience", "fee", "categories",
            "branch_tags", "subscription_tags", "subscription_tag_details",
            "subscription_catalog_version", "method", "error", "title_check")
    return {k: entry.get(k) for k in keys}


def main():
    ap = argparse.ArgumentParser(description="補正 2026-10-06 點名嘅 13 條通告（7 地域＋6 總會）")
    ap.add_argument("--dry-run", action="store_true", help="只顯示會改咩，唔寫檔")
    args = ap.parse_args()

    cache = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    enrich = json.loads(ENRICH_PATH.read_text(encoding="utf-8"))
    problems = []
    changes = []      # 會寫入嘅改動
    verifications = []  # 只核對、唔改嘅結果

    # ── 階段一：全部抽取結果先同官方 PDF 核實值比對（有任何一個唔啱即中止）──
    ekr_results = {}
    for wpdmdl, exp in EKR_EXPECTED.items():
        url = f"{EKR_BASE}{wpdmdl}"
        item = find_cache_item(cache, url)
        if item is None:
            problems.append(f"cache.json 搵唔到 {url}")
            continue
        if (item.get("title") or "") != exp["title"]:
            problems.append(f"{short_id(url)} 標題不符：cache={item.get('title')!r} 核實={exp['title']!r}")
            continue
        ekr_results[url] = extract_and_check(url, exp, "東九龍地域", problems)

    hq_results = {}
    for url, exp in HQ_FIXES.items():
        hq_results[url] = extract_and_check(url, exp, "總會", problems)

    if problems:
        print("❌ 抽取結果同官方 PDF 核實值不符——一個字都唔會寫入：")
        for p in problems:
            print("   •", p)
        sys.exit(1)

    # ── 階段二：寫入 7 條東九龍地域 entry（各自 PDF、各自來源、冇 derived_from）──
    for url, res in ekr_results.items():
        exp = EKR_EXPECTED[url.rsplit("=", 1)[-1]]
        check = reconcile_listing_title(exp["title"], exp["text"])
        new_entry = build_entry("東九龍地域", exp["title"], res, check.get("status") or "verified")
        old = enrich.get(url)
        if (entry_signature(old) == entry_signature(new_entry)
                and isinstance(old, dict) and old.get("enrich_version") == ENRICH_VERSION):
            continue
        enrich[url] = new_entry
        cats = "、".join(c.get("label", "") for c in new_entry["categories"])
        changes.append(
            f"enrich.json +{short_id(url)}（東九龍地域自己嘅 PDF）：{exp['title'][:26]}"
            f"｜{cats}｜截止={new_entry['deadline'] or '—'}"
            f"｜對象={new_entry['audience'] or '—'}｜費用={new_entry['fee'] or '—'}"
        )

    # ── 階段三：補正 4 條總會 entry（點名欄位＋由新對象重算嘅支部／訂閱標籤）──
    for url, exp in HQ_FIXES.items():
        res = hq_results[url]
        entry = enrich.get(url)
        if not isinstance(entry, dict):
            problems.append(f"enrich.json 搵唔到 {url}（總會補正對象）")
            continue
        if (entry.get("title") or "") != exp["title"]:
            problems.append(f"{short_id(url)} 標題不符：enrich={entry.get('title')!r} 核實={exp['title']!r}")
            continue
        before = {
            "deadline": entry.get("deadline", ""),
            "audience": entry.get("audience", ""),
            "fee": entry.get("fee", ""),
            "categories": [c.get("label") for c in (entry.get("categories") or [])],
            "subscription_tags": list(entry.get("subscription_tags") or []),
        }
        # 只補正欄位；標題／來源／method／error／title_check／listing_title 照舊
        entry["deadline"] = res.get("deadline", "")
        entry["audience"] = res.get("audience", "")
        entry["fee"] = normalize_fee(res.get("fee", ""))
        entry["categories"] = res.get("categories") or []
        entry["branch_tags"] = res.get("branch_tags") or []
        entry["subscription_tags"] = res.get("subscription_tags") or []
        entry["subscription_tag_details"] = res.get("subscription_tag_details") or []
        entry["subscription_catalog_version"] = res.get("subscription_catalog_version", "")
        entry["enriched_at"] = datetime.datetime.now(HKT).strftime("%Y-%m-%d %H:%M:%S")
        entry["enrich_version"] = ENRICH_VERSION
        diffs = [f"{k}：{before[k] or '—'} → {entry[k] or '—'}"
                 for k in ("deadline", "audience", "fee") if before[k] != entry[k]]
        if before["categories"] != [c.get("label") for c in entry["categories"]]:
            diffs.append(f"分類：{'、'.join(before['categories']) or '—'} → "
                         f"{'、'.join(c.get('label', '') for c in entry['categories'])}")
        if before["subscription_tags"] != entry["subscription_tags"]:
            diffs.append(f"訂閱標籤：{before['subscription_tags']} → {entry['subscription_tags']}")
        if diffs:
            changes.append(f"enrich.json 補正 {short_id(url)}（{exp['note']}）：" + "；".join(diffs))

    # ── 階段四：核對 26229／26232（現值正確就唔改）──
    for url, exp in HQ_VERIFY_ONLY.items():
        entry = enrich.get(url)
        if not isinstance(entry, dict):
            problems.append(f"enrich.json 搵唔到 {url}（核對對象）")
            continue
        cats = "、".join(c.get("label", "") for c in (entry.get("categories") or []))
        ok = (entry.get("deadline") == exp["deadline"] and cats == exp["category"]
              and (not exp.get("audience") or entry.get("audience", "") == exp["audience"]))
        if not ok:
            problems.append(
                f"{short_id(url)} 現值唔正確：截止={entry.get('deadline')!r} 分類={cats!r} "
                f"對象={entry.get('audience')!r}（官方 PDF 核實：{exp['deadline']}／"
                f"{exp['category']}／{exp.get('audience', '—')}）"
            )
        else:
            verifications.append(
                f"✓ 核對 {short_id(url)}：{exp['category']}／{exp['deadline']}"
                + (f"／{exp['audience']}" if exp.get("audience") else "")
                + " 現值正確，無須改"
            )

    # ── 階段五：鐵律檢查——enrich.json 唔可以有 derived_from ──
    derived = [u for u, v in enrich.items() if isinstance(v, dict) and "derived_from" in v]
    if derived:
        problems.append(f"enrich.json 仍有 derived_from entry：{[short_id(u) for u in derived[:3]]}…")

    if problems:
        print("❌ 發現問題，唔會寫入：")
        for p in problems:
            print("   •", p)
        sys.exit(1)

    for line in verifications:
        print(" •", line)
    if not changes:
        print("✅ 已經乾淨，冇嘢要改。" if not verifications else "✅ 除核對項外冇嘢要改。")
        return

    for line in changes:
        print(" •", line)
    print(f"\n合共 {len(changes)} 項改動。")

    if args.dry_run:
        print("（--dry-run：未寫入任何檔案）")
        return

    ENRICH_PATH.write_text(json.dumps(enrich, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"📝 已更新 {ENRICH_PATH.name}（cache.json 唔使改：列表標題本來就正確，"
          f"category 只住喺 enrich.json）")


if __name__ == "__main__":
    main()
