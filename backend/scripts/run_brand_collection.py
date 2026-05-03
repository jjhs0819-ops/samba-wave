#!/usr/bin/env python3
"""
브랜드 소싱 자동화 스크립트

사용법:
  SAMBA_EMAIL=user@example.com SAMBA_PASSWORD=pwd python scripts/run_brand_collection.py

흐름:
  1. 카테고리 스캔 → 그룹 생성 → 수집 Job 등록
  2. 수집 완료 대기
  3. AI 태깅
  4. 빈 그룹 삭제
"""

import asyncio
import os
import sys
import time
from datetime import datetime
from typing import Optional

import aiohttp

# 수집 대상 정의
COLLECTION_TARGETS = {
    'MUSINSA': [
        '아이더', '뉴발란스', '미즈노', '아디다스', '반스', '디스커버리', '크록스',
        '스노우피크', '예일', '휠라', '게스', '네파', '리바이스', '엄브로', '엠엘비',
        '오니츠카타이거', '지오다노', '커버낫', '케이투', '다이나핏', '노스페이스',
        '닥터마틴', '데상트', '디스이즈네버댓', '살로몬', '킨',
    ],
    'LOTTEON': [
        '스케쳐스', '크록스', '라코스테', '르꼬끄', '리바이스', '엄브로', '엠엘비',
        '지오다노', '커버낫', '케이투', '다이나핏', '내셔널지오그래픽', '노스페이스', '킨',
    ],
    'SSG': [
        '디스커버리', '스케쳐스', '크록스', '게스', '네파', '라코스테', '르꼬끄',
        '리바이스', '엄브로', '엠엘비', '지오다노', '커버낫', '케이투', '엘칸토', '금강제화',
    ],
    'GSSHOP': [
        '아이더', '크록스', '휠라', '다이나핏',
    ],
    'ABCmart': [
        '뉴발란스', '미즈노', '반스', '크록스', '휠라', '게스', '닥터마틴',
    ],
}

API_BASE = 'https://api.samba-wave.co.kr/api/v1'
POLLING_INTERVAL = 10  # 초
LOG_PREFIX = '[브랜드수집]'


def log(msg: str):
    ts = datetime.now().strftime('%H:%M:%S')
    print(f'{LOG_PREFIX} {ts} {msg}')


class SambaAPIClient:
    def __init__(self, base_url: str, access_token: str):
        self.base_url = base_url
        self.access_token = access_token
        self.created_group_ids = []

    async def request(self, method: str, path: str, json_data=None, params=None):
        """HTTP 요청 공통 메서드"""
        url = f'{self.base_url}{path}'
        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'Content-Type': 'application/json',
        }

        async with aiohttp.ClientSession() as session:
            try:
                async with session.request(
                    method, url, json=json_data, params=params, headers=headers, timeout=60
                ) as resp:
                    if resp.status >= 400:
                        text = await resp.text()
                        log(f'❌ {method} {path} {resp.status}: {text[:200]}')
                        return None
                    data = await resp.json()
                    return data
            except Exception as e:
                log(f'❌ 요청 실패: {path}, {e}')
                return None

    async def brand_scan(self, source_site: str, keyword: str = None, brand: str = None,
                         selected_brands: list = None, brand_ids: list = None):
        """카테고리 스캔"""
        payload = {
            'source_site': source_site,
            'gf': 'A',
        }
        if keyword:
            payload['keyword'] = keyword
        if brand:
            payload['brand'] = brand
        if selected_brands:
            payload['selected_brands'] = selected_brands
        if brand_ids:
            payload['brand_ids'] = brand_ids

        result = await self.request('POST', '/samba/collector/brand-scan', json_data=payload)
        if result and 'categories' in result:
            return result['categories']
        return []

    async def brand_discover(self, source_site: str, keyword: str):
        """브랜드 ID 발견 (LOTTEON, SSG 전용)"""
        payload = {'keyword': keyword, 'source_site': source_site}
        result = await self.request('POST', '/samba/collector/brand-discover', json_data=payload)
        if result:
            # LOTTEON: selected_brands, SSG: brand_ids
            return result.get('selected_brands') or result.get('brand_ids') or []
        return []

    async def brand_create_groups(self, source_site: str, brand_name: str, categories: list):
        """카테고리별 그룹 생성"""
        payload = {
            'source_site': source_site,
            'brand_name': brand_name,
            'categories': categories,
            'gf': 'A',
        }
        result = await self.request('POST', '/samba/collector/brand-create-groups',
                                     json_data=payload)
        if result and 'groups' in result:
            filter_ids = [g['id'] for g in result['groups']]
            self.created_group_ids.extend(filter_ids)
            return filter_ids
        return []

    async def brand_collect_all(self, source_site: str, filter_ids: list, keyword: str, brand: str):
        """수집 Job 등록 (brand-collect-all 엔드포인트 사용, 존재하면)"""
        payload = {
            'source_site': source_site,
            'filter_ids': filter_ids,
            'keyword': keyword,
            'brand': brand,
            'gf': 'A',
            'exclude_preorder': True,
            'exclude_boutique': True,
            'use_max_discount': False,
            'include_sold_out': False,
        }
        result = await self.request('POST', '/samba/collector/brand-collect-all',
                                     json_data=payload)
        if result and 'job_id' in result:
            return result['job_id']
        return None

    async def collect_filter(self, filter_id: str, group_index: int = 0, group_total: int = 0):
        """개별 필터 수집 (brand-collect-all 미지원 소싱처용)"""
        params = {}
        if group_index:
            params['group_index'] = group_index
        if group_total:
            params['group_total'] = group_total

        result = await self.request('POST', f'/samba/collector/collect-filter/{filter_id}',
                                     params=params)
        if result and 'job_id' in result:
            return result['job_id']
        return None

    async def poll_queue_status(self):
        """수집 Job 큐 상태 조회"""
        result = await self.request('GET', '/samba/jobs/collect-queue-status')
        if result:
            return result.get('running', []), result.get('pending', [])
        return [], []

    async def get_filters(self):
        """그룹 목록 조회"""
        result = await self.request('GET', '/samba/collector/filters')
        if isinstance(result, list):
            return result
        return []

    async def ai_tag_generate(self, group_ids: list):
        """AI 태그 생성 + 적용"""
        payload = {
            'group_ids': group_ids,
            'method': 'gemini',
        }
        result = await self.request('POST', '/samba/proxy/ai-tags/generate', json_data=payload)
        return result is not None

    async def delete_filter(self, filter_id: str):
        """그룹 삭제"""
        result = await self.request('DELETE', f'/samba/collector/filters/{filter_id}')
        return result is not None and result.get('ok')


async def login(email: str, password: str) -> Optional[str]:
    """로그인 후 access token 반환"""
    url = f'{API_BASE}/auth/email/login'
    payload = {'email': email, 'password': password}

    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(url, json=payload, timeout=30) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    token = data.get('app_auth_token')
                    if token:
                        log(f'✅ 로그인 성공')
                        return token
                else:
                    log(f'❌ 로그인 실패: {resp.status}')
        except Exception as e:
            log(f'❌ 로그인 요청 실패: {e}')
    return None


async def main():
    # 환경변수 확인
    email = os.getenv('SAMBA_EMAIL')
    password = os.getenv('SAMBA_PASSWORD')

    if not email or not password:
        log('❌ SAMBA_EMAIL, SAMBA_PASSWORD 환경변수 필수')
        sys.exit(1)

    # 로그인
    token = await login(email, password)
    if not token:
        sys.exit(1)

    client = SambaAPIClient(API_BASE, token)
    total_targets = sum(len(brands) for brands in COLLECTION_TARGETS.values())
    processed = 0

    log(f'🚀 시작: 총 {total_targets}개 브랜드×소싱처 조합')
    log('')

    # Phase 1: 스캔 → 그룹 생성 → 수집 Job 등록
    for source_site, brands in COLLECTION_TARGETS.items():
        log(f'📍 소싱처: {source_site}')

        for brand_name in brands:
            processed += 1
            log(f'  [{processed}/{total_targets}] {brand_name}...')

            # Step 1: 브랜드 발견 (LOTTEON/SSG는 먼저 발견)
            brand_ids = []
            if source_site in ('LOTTEON', 'SSG'):
                brand_ids = await client.brand_discover(source_site, brand_name)
                if not brand_ids:
                    log(f'    ⚠️  브랜드를 찾을 수 없음, 스킵')
                    continue

            # Step 2: 카테고리 스캔
            categories = await client.brand_scan(
                source_site=source_site,
                keyword=brand_name,
                selected_brands=brand_ids if source_site == 'LOTTEON' else None,
                brand_ids=brand_ids if source_site == 'SSG' else None,
            )

            if not categories:
                log(f'    ⚠️  카테고리 0개, 스킵')
                continue

            log(f'    📊 {len(categories)}개 카테고리 발견')

            # Step 3: 그룹 생성
            filter_ids = await client.brand_create_groups(source_site, brand_name, categories)

            if not filter_ids:
                log(f'    ❌ 그룹 생성 실패')
                continue

            log(f'    ✅ {len(filter_ids)}개 그룹 생성')

            # Step 4: 수집 Job 등록
            if source_site == 'LOTTEON':
                # LOTTEON은 brand-collect-all 미지원, 개별 filter 수집
                for idx, fid in enumerate(filter_ids):
                    job_id = await client.collect_filter(fid, idx + 1, len(filter_ids))
                    if job_id:
                        log(f'    📋 [{idx + 1}/{len(filter_ids)}] Job {job_id[:8]}... 등록')
            else:
                # MUSINSA, SSG, GSSHOP, ABCmart는 brand-collect-all
                job_id = await client.brand_collect_all(
                    source_site, filter_ids, brand_name, brand_name
                )
                if job_id:
                    log(f'    📋 Job {job_id[:8]}... 등록')

            await asyncio.sleep(0.5)  # API 레이트 리밋 고려

        log('')

    log(f'✅ Phase 1 완료: {len(client.created_group_ids)}개 그룹 생성')
    log('')

    # Phase 2: 수집 완료 대기
    log('⏳ Phase 2: 수집 완료 대기 중...')
    max_wait = 3600  # 1시간
    elapsed = 0

    while elapsed < max_wait:
        running, pending = await client.poll_queue_status()
        total_jobs = len(running) + len(pending)

        if total_jobs == 0:
            log('✅ 모든 수집 Job 완료')
            break

        # 진행 중인 Job 표시
        if running:
            for job in running:
                current = job.get('current', 0)
                total = job.get('total', 0)
                pct = f"{(current / total * 100):.0f}%" if total > 0 else "?"
                filter_name = job.get('filter_name', '?')
                log(f'  🔄 {filter_name}: {current}/{total} {pct}')

        # 대기 중인 Job 개수
        if pending:
            log(f'  ⏸️  대기 중: {len(pending)}개')

        await asyncio.sleep(POLLING_INTERVAL)
        elapsed += POLLING_INTERVAL

    if elapsed >= max_wait:
        log('⚠️  1시간 초과, 대기 종료 (백그라운드 계속 실행)')

    log('')

    # Phase 3: AI 태깅
    log('🤖 Phase 3: AI 태깅 시작...')

    # 생성된 그룹 중 수집된 상품이 있는 그룹만 필터링
    all_filters = await client.get_filters()
    tagged_group_ids = []

    if all_filters:
        for f in all_filters:
            if f['id'] in client.created_group_ids and f.get('collected_count', 0) > 0:
                tagged_group_ids.append(f['id'])

        if tagged_group_ids:
            log(f'  📊 {len(tagged_group_ids)}개 그룹에 AI 태그 적용')
            # AI 태그 생성 (배치 크기 제한)
            batch_size = 20
            for i in range(0, len(tagged_group_ids), batch_size):
                batch = tagged_group_ids[i:i + batch_size]
                success = await client.ai_tag_generate(batch)
                if success:
                    log(f'  ✅ [{i + 1}/{len(tagged_group_ids)}] AI 태그 적용 완료')
                await asyncio.sleep(1)
        else:
            log('  ℹ️  수집된 상품이 있는 그룹 없음, 스킵')
    else:
        log('  ⚠️  그룹 목록 조회 실패')

    log('')

    # Phase 4: 빈 그룹 삭제
    log('🗑️  Phase 4: 빈 그룹 삭제...')

    all_filters = await client.get_filters()
    empty_groups = [f for f in all_filters if f['id'] in client.created_group_ids
                    and f.get('collected_count', 0) == 0]

    if empty_groups:
        log(f'  🔍 {len(empty_groups)}개 빈 그룹 발견')
        for i, f in enumerate(empty_groups):
            success = await client.delete_filter(f['id'])
            if success:
                log(f'  ✅ [{i + 1}/{len(empty_groups)}] {f["name"]} 삭제')
                await asyncio.sleep(0.3)
    else:
        log('  ℹ️  빈 그룹 없음')

    log('')
    log('🎉 완료!')


if __name__ == '__main__':
    asyncio.run(main())
