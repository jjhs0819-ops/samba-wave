"""모음전(Pick A Card) 멀티 배리에이션 리스팅 생성 [컨테이너 실행].

왜 Trading API 인가:
  Inventory API 는 카테고리 taxonomy 가 "변형 가능"으로 지정한 항목으로만 배리에이션을
  만들 수 있는데, 183454(TCG 싱글)는 Franchise / Customized 둘뿐이라 카드별 선택을
  만들 수 없다. 경쟁사 "Choose Your Card" 리스팅들은 전부 Trading API 의
  커스텀 VariationSpecifics("Pick A Card")를 쓴다. (2026-07-23 taxonomy 실조회로 확인)

용도: 낱장 커먼을 저가로 묶어 판매건수(주문이행 지표)를 올리는 모음전.

실행:
  docker exec local-samba-api-1 /app/backend/.venv/bin/python3 \
      /tmp/multivar_listing.py [--price 0.10] [--dry]
"""

import asyncio
import io
import json
import sys
import xml.etree.ElementTree as ET

import httpx

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, "/app/backend")

TENANT = "tn_01KRX6H1Q97JGPXRPB011985QT"
KV = "ma_01KXQCB67RZBBE99H8TM2J4K8J"  # k-tcg_vault 전용
NS = "{urn:ebay:apis:eBLBaseComponents}"
CATEGORY = "183454"
TITLE = "Pokemon Card Korean Japanese Single - Choose Your Card! Complete Your Set"

# (변형 이름, 언어) — 사진 순서와 1:1 대응
CARDS = [
    ("Sigilyph 039/098 s12", "Korean"),
    ("Raichu 025/098 s12", "Korean"),
    ("Heliolisk 031/098 s12", "Korean"),
    ("Zeraora 032/098 s12", "Korean"),
    ("Torracat 016/098 s12", "Korean"),
    ("Stonjourner 055/098 s12", "Korean"),
    ("Dratini 070/098 s12", "Korean"),
    ("Snorunt 019/098 s12", "Korean"),
    ("Rapidash 011/098 s12", "Korean"),
    ("Mandibuzz 048/081 m5", "Japanese"),
    ("Muku Supporter 078/081 m5", "Japanese"),
    ("Mankey 040/081 m5", "Japanese"),
    ("Tropius 001/081 m5", "Japanese"),
    ("Seaking 013/081 m5", "Japanese"),
    ("Victini 012/098 s12", "Korean"),
]


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


async def main():
    import backend.main  # noqa: F401
    from backend.core.tenant_context import current_tenant_id
    from backend.db.orm import get_write_session
    from backend.domain.samba.account.model import SambaMarketAccount
    from backend.domain.samba.account.resolver import resolve_market_creds
    from backend.domain.samba.proxy.ebay import EbayClient
    from sqlalchemy import text as t
    from sqlmodel import select

    # [중요] eBay 최소 판매가는 $0.99 다. 그 아래로 넣으면 등록 자체가 거부된다.
    price = sys.argv[sys.argv.index("--price") + 1] if "--price" in sys.argv else "0.99"
    dry = "--dry" in sys.argv
    urls = json.load(open("/tmp/card_urls.json", encoding="utf-8"))
    assert len(urls) == len(CARDS), f"사진 {len(urls)}장 ≠ 카드 {len(CARDS)}장"

    tok = current_tenant_id.set(TENANT)
    try:
        async with get_write_session() as s:
            acc = (
                (
                    await s.execute(
                        select(SambaMarketAccount).where(SambaMarketAccount.id == KV)
                    )
                )
                .scalars()
                .first()
            )
            ax = getattr(acc, "additional_fields", None) or {}
            cr = (
                await resolve_market_creds(
                    s, TENANT, market_type="ebay", store_key="store_ebay"
                )
                or {}
            )
            ec = EbayClient(
                cr.get("clientId")
                or cr.get("appId")
                or ax.get("clientId")
                or ax.get("appId", ""),
                cr.get("devId") or ax.get("devId", ""),
                cr.get("clientSecret")
                or cr.get("certId")
                or ax.get("clientSecret")
                or ax.get("certId", ""),
                cr.get("oauthToken")
                or cr.get("authToken")
                or ax.get("oauthToken")
                or ax.get("authToken", ""),
            )
            tk = await ec._get_access_token()

            row = (
                await s.execute(
                    t(
                        "SELECT top_html, top_image_s3_key FROM samba_detail_template WHERE id='dt_kpopcard_v1'"
                    )
                )
            ).first()
            desc = (row[0] or "") or (
                '<div style="max-width:900px;margin:0 auto;">'
                f'<img src="{row[1]}" style="width:100%;display:block;"></div>'
            )

            variations = "".join(
                "<Variation>"
                f"<SKU>MULTI-{i + 1:02d}</SKU>"
                f"<StartPrice>{price}</StartPrice>"
                "<Quantity>1</Quantity>"
                "<VariationSpecifics><NameValueList><Name>Pick A Card</Name>"
                f"<Value>{esc(name)}</Value></NameValueList></VariationSpecifics>"
                "</Variation>"
                for i, (name, _lang) in enumerate(CARDS)
            )
            pic_sets = "".join(
                "<VariationSpecificPictureSet>"
                f"<VariationSpecificValue>{esc(name)}</VariationSpecificValue>"
                f"<PictureURL>{esc(urls[i])}</PictureURL>"
                "</VariationSpecificPictureSet>"
                for i, (name, _lang) in enumerate(CARDS)
            )
            xml = (
                '<?xml version="1.0" encoding="utf-8"?>'
                '<AddFixedPriceItemRequest xmlns="urn:ebay:apis:eBLBaseComponents"><Item>'
                f"<Title>{esc(TITLE[:80])}</Title>"
                f"<Description><![CDATA[{desc}]]></Description>"
                f"<PrimaryCategory><CategoryID>{CATEGORY}</CategoryID></PrimaryCategory>"
                "<ConditionID>4000</ConditionID>"
                "<ConditionDescriptors><ConditionDescriptor>"
                "<Name>40001</Name><Value>400010</Value>"
                "</ConditionDescriptor></ConditionDescriptors>"
                "<Country>KR</Country><Currency>USD</Currency>"
                "<ListingDuration>GTC</ListingDuration><ListingType>FixedPriceItem</ListingType>"
                "<Site>US</Site><DispatchTimeMax>4</DispatchTimeMax>"
                f"<PostalCode>{esc(str(ax.get('postalCode') or '04524'))}</PostalCode>"
                "<Location>Seoul, South Korea</Location>"
                "<ItemSpecifics>"
                "<NameValueList><Name>Game</Name><Value>Pok&#233;mon TCG</Value></NameValueList>"
                "<NameValueList><Name>Card Type</Name><Value>Pok&#233;mon</Value></NameValueList>"
                "<NameValueList><Name>Manufacturer</Name>"
                "<Value>The Pok&#233;mon Company</Value></NameValueList>"
                "<NameValueList><Name>Age Level</Name><Value>6+</Value></NameValueList>"
                # eBay 는 Language 를 값 1개만 받는다(다국어 혼합 모음전이라도).
                # 한글판이 다수라 Korean 고정, 일어판 여부는 변형 이름의 세트코드로 구분.
                "<NameValueList><Name>Language</Name><Value>Korean</Value></NameValueList>"
                "<NameValueList><Name>Graded</Name><Value>No</Value></NameValueList>"
                "<NameValueList><Name>California Prop 65 Warning</Name>"
                "<Value>No warning applicable</Value></NameValueList>"
                "</ItemSpecifics>"
                "<SellerProfiles>"
                f"<SellerShippingProfile><ShippingProfileID>{ax.get('fulfillmentPolicyId', '')}"
                "</ShippingProfileID></SellerShippingProfile>"
                f"<SellerPaymentProfile><PaymentProfileID>{ax.get('paymentPolicyId', '')}"
                "</PaymentProfileID></SellerPaymentProfile>"
                f"<SellerReturnProfile><ReturnProfileID>{ax.get('returnPolicyId', '')}"
                "</ReturnProfileID></SellerReturnProfile>"
                "</SellerProfiles>"
                "<PictureDetails>"
                + "".join(f"<PictureURL>{esc(u)}</PictureURL>" for u in urls[:12])
                + "</PictureDetails>"
                "<Variations>"
                "<VariationSpecificsSet><NameValueList><Name>Pick A Card</Name>"
                + "".join(f"<Value>{esc(n)}</Value>" for n, _ in CARDS)
                + "</NameValueList></VariationSpecificsSet>"
                + variations
                + "<Pictures><VariationSpecificName>Pick A Card</VariationSpecificName>"
                + pic_sets
                + "</Pictures>"
                "</Variations>"
                "</Item></AddFixedPriceItemRequest>"
            )
            if dry:
                print(
                    f"[DRY] 변형 {len(CARDS)}개 / 개당 ${price} / 카테고리 {CATEGORY}"
                )
                for n, _ in CARDS:
                    print("   ", n)
                return

            hdr = {
                "X-EBAY-API-CALL-NAME": "AddFixedPriceItem",
                "X-EBAY-API-SITEID": "0",
                "X-EBAY-API-COMPATIBILITY-LEVEL": "1349",
                "X-EBAY-API-IAF-TOKEN": tk,
                "Content-Type": "text/xml",
            }
            async with httpx.AsyncClient(timeout=120) as c:
                r = await c.post(
                    f"{ec._base_url}/ws/api.dll",
                    content=xml.encode("utf-8"),
                    headers=hdr,
                )
            root = ET.fromstring(r.text)
            ack = root.findtext(f".//{NS}Ack", "")
            print("Ack", ack, "| ItemID", root.findtext(f".//{NS}ItemID", "-"))
            for e in root.findall(f".//{NS}Errors"):
                sev = e.findtext(f"{NS}SeverityCode", "")
                msg = e.findtext(f"{NS}LongMessage", "")
                print(f"  [{sev}] {msg[:180]}")
    finally:
        current_tenant_id.reset(tok)


asyncio.run(main())
