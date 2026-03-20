"""SambaWave Category service."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

from backend.domain.samba.category.model import SambaCategoryMapping, SambaCategoryTree
from backend.domain.samba.category.repository import (
    SambaCategoryMappingRepository,
    SambaCategoryTreeRepository,
)

logger = logging.getLogger(__name__)

# 마켓별 카테고리 데이터 (검색/추천용 참조 목록)
# AI 매핑 시에는 이 목록을 참고하되, 목록에 없는 카테고리도 AI가 생성 가능
MARKET_CATEGORIES: Dict[str, List[str]] = {
    "smartstore": [
        # 남성의류
        "패션의류 > 남성의류 > 티셔츠",
        "패션의류 > 남성의류 > 긴팔 티셔츠",
        "패션의류 > 남성의류 > 셔츠",
        "패션의류 > 남성의류 > 니트/스웨터",
        "패션의류 > 남성의류 > 맨투맨/후드",
        "패션의류 > 남성의류 > 청바지",
        "패션의류 > 남성의류 > 슬랙스/팬츠",
        "패션의류 > 남성의류 > 반바지/숏팬츠",
        "패션의류 > 남성의류 > 아우터 > 자켓",
        "패션의류 > 남성의류 > 아우터 > 점퍼",
        "패션의류 > 남성의류 > 아우터 > 패딩",
        "패션의류 > 남성의류 > 아우터 > 코트",
        "패션의류 > 남성의류 > 정장",
        # 여성의류
        "패션의류 > 여성의류 > 원피스",
        "패션의류 > 여성의류 > 블라우스",
        "패션의류 > 여성의류 > 니트/스웨터",
        "패션의류 > 여성의류 > 티셔츠",
        "패션의류 > 여성의류 > 스커트",
        "패션의류 > 여성의류 > 팬츠/청바지",
        "패션의류 > 여성의류 > 아우터 > 자켓",
        "패션의류 > 여성의류 > 아우터 > 코트",
        "패션의류 > 여성의류 > 아우터 > 패딩",
        # 신발
        "패션의류 > 남성신발 > 스니커즈",
        "패션의류 > 남성신발 > 운동화",
        "패션의류 > 남성신발 > 구두/로퍼",
        "패션의류 > 남성신발 > 샌들/슬리퍼",
        "패션의류 > 남성신발 > 부츠",
        "패션의류 > 여성신발 > 스니커즈",
        "패션의류 > 여성신발 > 부츠",
        "패션의류 > 여성신발 > 힐/펌프스",
        "패션의류 > 여성신발 > 플랫/로퍼",
        "패션의류 > 여성신발 > 샌들/슬리퍼",
        # 가방
        "패션잡화 > 가방 > 백팩",
        "패션잡화 > 가방 > 크로스백",
        "패션잡화 > 가방 > 토트백",
        "패션잡화 > 가방 > 숄더백",
        "패션잡화 > 가방 > 클러치/파우치",
        "패션잡화 > 가방 > 에코백/캔버스백",
        "패션잡화 > 가방 > 여행용 가방",
        "패션잡화 > 가방 > 서류가방/브리프케이스",
        "패션잡화 > 가방 > 힙색/웨이스트백",
        # 잡화
        "패션잡화 > 모자",
        "패션잡화 > 양말",
        "패션잡화 > 벨트",
        "패션잡화 > 지갑",
        "패션잡화 > 시계",
        "패션잡화 > 선글라스/안경",
        "패션잡화 > 스카프/머플러",
        "패션잡화 > 넥타이",
        # 스포츠
        "스포츠/레저 > 스포츠의류 > 상의",
        "스포츠/레저 > 스포츠의류 > 하의",
        "스포츠/레저 > 스포츠의류 > 세트",
        "스포츠/레저 > 스포츠신발 > 운동화",
        "스포츠/레저 > 스포츠신발 > 런닝화",
        "스포츠/레저 > 스포츠신발 > 축구화",
        "스포츠/레저 > 스포츠신발 > 등산화",
        "스포츠/레저 > 스포츠가방 > 스포츠백팩",
        "스포츠/레저 > 아웃도어 > 등산의류",
        "스포츠/레저 > 아웃도어 > 등산장비",
        # 뷰티
        "뷰티 > 스킨케어 > 토너",
        "뷰티 > 스킨케어 > 에센스",
        "뷰티 > 스킨케어 > 세럼/앰플",
        "뷰티 > 스킨케어 > 크림/로션",
        "뷰티 > 스킨케어 > 아이크림",
        "뷰티 > 스킨케어 > 클렌징",
        "뷰티 > 선케어 > 선크림",
        "뷰티 > 메이크업 > 립스틱",
        "뷰티 > 메이크업 > 파운데이션",
        "뷰티 > 헤어케어 > 샴푸",
        "뷰티 > 바디케어 > 바디워시",
        "뷰티 > 향수",
    ],
    "coupang": [
        # 남성의류
        "패션 > 남성의류 > 상의 > 반팔 티셔츠",
        "패션 > 남성의류 > 상의 > 긴팔 티셔츠",
        "패션 > 남성의류 > 상의 > 셔츠",
        "패션 > 남성의류 > 상의 > 니트/스웨터",
        "패션 > 남성의류 > 상의 > 맨투맨/후드티",
        "패션 > 남성의류 > 하의 > 청바지",
        "패션 > 남성의류 > 하의 > 슬랙스",
        "패션 > 남성의류 > 하의 > 반바지",
        "패션 > 남성의류 > 아우터 > 자켓",
        "패션 > 남성의류 > 아우터 > 점퍼/블루종",
        "패션 > 남성의류 > 아우터 > 패딩",
        "패션 > 남성의류 > 아우터 > 코트",
        # 여성의류
        "패션 > 여성의류 > 원피스",
        "패션 > 여성의류 > 블라우스/셔츠",
        "패션 > 여성의류 > 니트/스웨터",
        "패션 > 여성의류 > 티셔츠",
        "패션 > 여성의류 > 스커트",
        "패션 > 여성의류 > 팬츠/청바지",
        "패션 > 여성의류 > 아우터 > 자켓",
        "패션 > 여성의류 > 아우터 > 코트",
        "패션 > 여성의류 > 아우터 > 패딩",
        # 신발
        "패션 > 신발 > 운동화 > 스니커즈",
        "패션 > 신발 > 운동화 > 런닝화",
        "패션 > 신발 > 운동화 > 워킹화",
        "패션 > 신발 > 구두/로퍼",
        "패션 > 신발 > 부츠",
        "패션 > 신발 > 샌들/슬리퍼",
        "패션 > 신발 > 실내화",
        # 가방
        "패션의류잡화 > 여성패션 > 여성잡화 > 가방",
        "패션의류잡화 > 여성패션 > 여성잡화 > 가방 > 여성비치백/왕골가방",
        "패션의류잡화 > 여성패션 > 여성잡화 > 가방 > 여성기타캐주얼가방",
        "패션의류잡화 > 여성패션 > 여성잡화 > 가방 > 여성가방액세서리",
        "패션의류잡화 > 여성패션 > 여성잡화 > 해외직구 > 가방",
        "패션의류잡화 > 남성패션 > 남성가방 > 백팩",
        "패션의류잡화 > 남성패션 > 남성가방 > 크로스백",
        "패션의류잡화 > 남성패션 > 남성가방 > 토트백",
        "패션의류잡화 > 남성패션 > 남성가방 > 숄더백",
        "패션의류잡화 > 남성패션 > 남성가방 > 클러치/파우치",
        "패션의류잡화 > 남성패션 > 남성가방 > 서류가방/브리프케이스",
        "패션의류잡화 > 여성패션 > 여성가방 > 백팩",
        "패션의류잡화 > 여성패션 > 여성가방 > 크로스백",
        "패션의류잡화 > 여성패션 > 여성가방 > 토트백",
        "패션의류잡화 > 여성패션 > 여성가방 > 숄더백",
        "패션의류잡화 > 여성패션 > 여성가방 > 클러치/파우치",
        "패션의류잡화 > 여성패션 > 여성가방 > 에코백",
        "여행/레저 > 여행용가방 > 캐리어",
        "여행/레저 > 여행용가방 > 보스턴백",
        "스포츠 > 스포츠가방 > 스포츠백팩",
        "스포츠 > 스포츠가방 > 짐백/더플백",
        # 잡화
        "패션 > 패션잡화 > 모자",
        "패션 > 패션잡화 > 양말",
        "패션 > 패션잡화 > 벨트",
        "패션 > 패션잡화 > 지갑",
        "패션 > 패션잡화 > 시계",
        "패션 > 패션잡화 > 선글라스",
        "패션 > 패션잡화 > 스카프/머플러",
        # 스포츠
        "스포츠/레저 > 스포츠의류 > 남성 상의",
        "스포츠/레저 > 스포츠의류 > 남성 하의",
        "스포츠/레저 > 스포츠의류 > 여성 상의",
        "스포츠/레저 > 스포츠신발 > 런닝화",
        "스포츠/레저 > 스포츠신발 > 축구화",
        "스포츠/레저 > 스포츠신발 > 등산화",
        "스포츠/레저 > 아웃도어 > 등산의류",
        "스포츠/레저 > 아웃도어 > 등산장비",
        # 뷰티
        "뷰티 > 스킨케어 > 세럼/에센스",
        "뷰티 > 스킨케어 > 토너/스킨",
        "뷰티 > 스킨케어 > 크림/로션",
        "뷰티 > 스킨케어 > 클렌징",
        "뷰티 > 선케어 > 선크림",
        "뷰티 > 메이크업 > 립스틱",
        "뷰티 > 메이크업 > 파운데이션",
        "뷰티 > 헤어케어 > 샴푸",
        "뷰티 > 바디케어 > 바디워시",
        "뷰티 > 향수",
    ],
    "gmarket": [
        "의류/패션 > 남성의류 > 티셔츠/반팔",
        "의류/패션 > 남성의류 > 긴팔/셔츠",
        "의류/패션 > 남성의류 > 니트/스웨터",
        "의류/패션 > 남성의류 > 맨투맨/후드",
        "의류/패션 > 남성의류 > 청바지/팬츠",
        "의류/패션 > 남성의류 > 반바지",
        "의류/패션 > 남성의류 > 아우터/자켓",
        "의류/패션 > 남성의류 > 패딩/점퍼",
        "의류/패션 > 남성의류 > 코트",
        "의류/패션 > 여성의류 > 원피스/스커트",
        "의류/패션 > 여성의류 > 블라우스/셔츠",
        "의류/패션 > 여성의류 > 니트/스웨터",
        "의류/패션 > 여성의류 > 티셔츠",
        "의류/패션 > 여성의류 > 팬츠/청바지",
        "의류/패션 > 여성의류 > 아우터/자켓",
        "의류/패션 > 남성신발 > 운동화",
        "의류/패션 > 남성신발 > 스니커즈",
        "의류/패션 > 남성신발 > 구두/로퍼",
        "의류/패션 > 남성신발 > 샌들/슬리퍼",
        "의류/패션 > 남성신발 > 부츠",
        "의류/패션 > 여성신발 > 부츠/힐",
        "의류/패션 > 여성신발 > 스니커즈",
        "의류/패션 > 여성신발 > 플랫/로퍼",
        "의류/패션 > 여성신발 > 샌들/슬리퍼",
        "패션잡화 > 가방 > 백팩",
        "패션잡화 > 가방 > 크로스백",
        "패션잡화 > 가방 > 토트백",
        "패션잡화 > 가방 > 숄더백",
        "패션잡화 > 가방 > 클러치/파우치",
        "패션잡화 > 가방 > 에코백",
        "패션잡화 > 가방 > 여행용 가방",
        "패션잡화 > 모자",
        "패션잡화 > 양말",
        "패션잡화 > 지갑",
        "패션잡화 > 벨트",
        "패션잡화 > 시계",
        "뷰티/화장품 > 스킨케어 > 에센스/세럼",
        "뷰티/화장품 > 스킨케어 > 토너",
        "뷰티/화장품 > 스킨케어 > 크림",
        "뷰티/화장품 > 선케어 > 선크림",
        "뷰티/화장품 > 메이크업 > 립스틱",
        "스포츠/레저 > 운동화 > 런닝화",
        "스포츠/레저 > 스포츠의류 > 상의",
        "스포츠/레저 > 스포츠의류 > 하의",
        "스포츠/레저 > 아웃도어 > 등산의류",
    ],
    "auction": [
        "패션/의류 > 남성의류 > 티셔츠",
        "패션/의류 > 남성의류 > 셔츠",
        "패션/의류 > 남성의류 > 니트/스웨터",
        "패션/의류 > 남성의류 > 맨투맨/후드",
        "패션/의류 > 남성의류 > 청바지/팬츠",
        "패션/의류 > 남성의류 > 아우터/자켓",
        "패션/의류 > 남성의류 > 패딩",
        "패션/의류 > 여성의류 > 원피스",
        "패션/의류 > 여성의류 > 블라우스/셔츠",
        "패션/의류 > 여성의류 > 니트/스웨터",
        "패션/의류 > 여성의류 > 팬츠/청바지",
        "패션/의류 > 여성의류 > 아우터",
        "패션/의류 > 남성신발 > 운동화/스니커즈",
        "패션/의류 > 남성신발 > 구두/로퍼",
        "패션/의류 > 남성신발 > 부츠",
        "패션/의류 > 여성신발 > 부츠/워커",
        "패션/의류 > 여성신발 > 스니커즈",
        "패션/의류 > 여성신발 > 힐/펌프스",
        "패션잡화 > 가방 > 백팩",
        "패션잡화 > 가방 > 크로스백",
        "패션잡화 > 가방 > 토트백",
        "패션잡화 > 가방 > 숄더백",
        "패션잡화 > 가방 > 클러치/파우치",
        "패션잡화 > 가방 > 에코백",
        "패션잡화 > 가방 > 여행용 가방",
        "패션잡화 > 모자",
        "패션잡화 > 양말",
        "패션잡화 > 지갑",
        "패션잡화 > 벨트",
        "뷰티/화장품 > 스킨케어 > 에센스/세럼",
        "뷰티/화장품 > 스킨케어 > 토너",
        "뷰티/화장품 > 선케어 > 선크림",
        "스포츠/레저 > 스포츠의류 > 운동복 상의",
        "스포츠/레저 > 스포츠의류 > 운동복 하의",
        "스포츠/레저 > 스포츠신발 > 운동화",
        "스포츠/레저 > 스포츠신발 > 런닝화",
    ],
    "11st": [
        "패션 > 남성의류 > 반팔 티셔츠",
        "패션 > 남성의류 > 긴팔 티셔츠",
        "패션 > 남성의류 > 셔츠",
        "패션 > 남성의류 > 니트/스웨터",
        "패션 > 남성의류 > 맨투맨/후드",
        "패션 > 남성의류 > 청바지",
        "패션 > 남성의류 > 슬랙스/팬츠",
        "패션 > 남성의류 > 아우터",
        "패션 > 남성의류 > 패딩",
        "패션 > 여성의류 > 원피스",
        "패션 > 여성의류 > 블라우스",
        "패션 > 여성의류 > 니트/스웨터",
        "패션 > 여성의류 > 팬츠/청바지",
        "패션 > 여성의류 > 아우터",
        "패션 > 남성신발 > 스니커즈",
        "패션 > 남성신발 > 구두/로퍼",
        "패션 > 여성신발 > 부츠",
        "패션 > 여성신발 > 스니커즈",
        "패션잡화 > 가방 > 백팩",
        "패션잡화 > 가방 > 크로스백",
        "패션잡화 > 가방 > 토트백",
        "패션잡화 > 가방 > 숄더백",
        "패션잡화 > 가방 > 클러치/파우치",
        "패션잡화 > 가방 > 여행용 가방",
        "패션잡화 > 모자",
        "패션잡화 > 양말",
        "패션잡화 > 지갑",
        "뷰티 > 스킨케어 > 토너/스킨",
        "뷰티 > 스킨케어 > 에센스/세럼",
        "뷰티 > 스킨케어 > 크림",
        "뷰티 > 선케어 > 선크림/선블록",
        "뷰티 > 메이크업 > 립스틱",
        "스포츠/레저 > 스포츠의류 > 상의",
        "스포츠/레저 > 스포츠의류 > 하의",
        "스포츠/레저 > 스포츠신발 > 런닝화",
        "스포츠/레저 > 아웃도어 > 등산의류",
    ],
    "ssg": [
        "패션 > 남성패션 > 티셔츠",
        "패션 > 남성패션 > 셔츠",
        "패션 > 남성패션 > 니트/스웨터",
        "패션 > 남성패션 > 맨투맨/후드",
        "패션 > 남성패션 > 청바지",
        "패션 > 남성패션 > 슬랙스/팬츠",
        "패션 > 남성패션 > 아우터/자켓",
        "패션 > 남성패션 > 패딩",
        "패션 > 여성패션 > 원피스",
        "패션 > 여성패션 > 블라우스",
        "패션 > 여성패션 > 니트/스웨터",
        "패션 > 여성패션 > 팬츠/청바지",
        "패션 > 여성패션 > 아우터",
        "패션 > 신발 > 스니커즈",
        "패션 > 신발 > 구두/로퍼",
        "패션 > 신발 > 부츠",
        "패션 > 신발 > 샌들/슬리퍼",
        "패션잡화 > 가방 > 백팩",
        "패션잡화 > 가방 > 크로스백",
        "패션잡화 > 가방 > 토트백",
        "패션잡화 > 가방 > 숄더백",
        "패션잡화 > 가방 > 클러치/파우치",
        "패션잡화 > 가방 > 여행용 가방",
        "패션잡화 > 모자",
        "패션잡화 > 양말",
        "패션잡화 > 지갑",
        "스포츠/아웃도어 > 스포츠신발 > 런닝화",
        "스포츠/아웃도어 > 스포츠의류 > 상의",
        "스포츠/아웃도어 > 스포츠의류 > 하의",
        "스포츠/아웃도어 > 등산 > 등산의류",
        "뷰티/헬스 > 기초화장품 > 에센스",
        "뷰티/헬스 > 기초화장품 > 토너",
        "뷰티/헬스 > 기초화장품 > 크림",
        "뷰티/헬스 > 선케어 > 선크림",
        "뷰티/헬스 > 메이크업 > 립스틱",
    ],
    "lotteon": [
        "패션/뷰티 > 남성패션 > 티셔츠",
        "패션/뷰티 > 남성패션 > 셔츠",
        "패션/뷰티 > 남성패션 > 니트/스웨터",
        "패션/뷰티 > 남성패션 > 맨투맨/후드",
        "패션/뷰티 > 남성패션 > 팬츠/청바지",
        "패션/뷰티 > 남성패션 > 아우터",
        "패션/뷰티 > 여성패션 > 원피스",
        "패션/뷰티 > 여성패션 > 블라우스",
        "패션/뷰티 > 여성패션 > 니트/스웨터",
        "패션/뷰티 > 여성패션 > 팬츠/청바지",
        "패션/뷰티 > 여성패션 > 아우터",
        "패션/뷰티 > 남성신발 > 스니커즈",
        "패션/뷰티 > 남성신발 > 구두/로퍼",
        "패션/뷰티 > 여성신발 > 부츠",
        "패션/뷰티 > 여성신발 > 스니커즈",
        "패션/뷰티 > 가방 > 백팩",
        "패션/뷰티 > 가방 > 크로스백",
        "패션/뷰티 > 가방 > 토트백",
        "패션/뷰티 > 가방 > 숄더백",
        "패션/뷰티 > 가방 > 클러치/파우치",
        "패션/뷰티 > 가방 > 여행용 가방",
        "패션/뷰티 > 잡화 > 모자",
        "패션/뷰티 > 잡화 > 양말",
        "패션/뷰티 > 잡화 > 지갑",
        "뷰티 > 스킨케어 > 에센스",
        "뷰티 > 스킨케어 > 토너",
        "뷰티 > 선케어 > 선크림",
        "스포츠/레저 > 스포츠의류 > 상의",
        "스포츠/레저 > 스포츠의류 > 하의",
        "스포츠/레저 > 스포츠신발 > 운동화",
    ],
    "lottehome": [
        "패션 > 남성의류 > 티셔츠",
        "패션 > 남성의류 > 셔츠",
        "패션 > 남성의류 > 팬츠",
        "패션 > 남성의류 > 아우터",
        "패션 > 여성의류 > 원피스",
        "패션 > 여성의류 > 블라우스",
        "패션 > 여성의류 > 팬츠",
        "패션 > 여성의류 > 아우터",
        "패션 > 신발 > 스니커즈",
        "패션 > 신발 > 구두/로퍼",
        "패션 > 신발 > 부츠",
        "패션 > 가방 > 백팩",
        "패션 > 가방 > 크로스백",
        "패션 > 가방 > 토트백",
        "패션 > 가방 > 숄더백",
        "패션 > 가방 > 여행용 가방",
        "패션 > 잡화 > 모자",
        "패션 > 잡화 > 지갑",
        "뷰티 > 기초케어 > 에센스/세럼",
        "뷰티 > 기초케어 > 크림",
        "뷰티 > 선케어 > 선크림",
        "스포츠 > 스포츠의류 > 상의",
        "스포츠 > 스포츠의류 > 하의",
        "스포츠 > 운동화 > 런닝화",
    ],
    "gsshop": [
        "패션 > 남성의류 > 티셔츠/반팔",
        "패션 > 남성의류 > 셔츠",
        "패션 > 남성의류 > 니트/스웨터",
        "패션 > 남성의류 > 바지/팬츠",
        "패션 > 남성의류 > 아우터/점퍼",
        "패션 > 여성의류 > 원피스",
        "패션 > 여성의류 > 블라우스",
        "패션 > 여성의류 > 니트/스웨터",
        "패션 > 여성의류 > 팬츠",
        "패션 > 여성의류 > 아우터",
        "패션 > 남성신발 > 스니커즈/운동화",
        "패션 > 남성신발 > 구두/로퍼",
        "패션 > 여성신발 > 부츠/워커",
        "패션 > 여성신발 > 스니커즈",
        "패션잡화 > 가방 > 백팩/배낭",
        "패션잡화 > 가방 > 크로스백",
        "패션잡화 > 가방 > 토트백",
        "패션잡화 > 가방 > 숄더백",
        "패션잡화 > 가방 > 클러치/파우치",
        "패션잡화 > 가방 > 여행용 가방",
        "패션잡화 > 모자",
        "패션잡화 > 양말",
        "패션잡화 > 지갑",
        "뷰티 > 스킨케어 > 에센스/앰플",
        "뷰티 > 스킨케어 > 토너",
        "뷰티 > 선케어 > 선크림",
        "스포츠/아웃도어 > 스포츠웨어 > 상의",
        "스포츠/아웃도어 > 스포츠웨어 > 하의",
        "스포츠/아웃도어 > 운동화 > 런닝화",
    ],
    "homeand": [
        "패션 > 남성의류 > 티셔츠",
        "패션 > 남성의류 > 셔츠",
        "패션 > 남성의류 > 팬츠",
        "패션 > 남성의류 > 아우터",
        "패션 > 여성의류 > 원피스",
        "패션 > 여성의류 > 블라우스",
        "패션 > 여성의류 > 팬츠",
        "패션 > 여성의류 > 아우터",
        "패션 > 신발 > 스니커즈",
        "패션 > 신발 > 구두/로퍼",
        "패션 > 신발 > 부츠",
        "패션 > 가방 > 백팩",
        "패션 > 가방 > 크로스백",
        "패션 > 가방 > 토트백",
        "패션 > 가방 > 숄더백",
        "패션 > 가방 > 여행용 가방",
        "패션 > 잡화 > 모자",
        "패션 > 잡화 > 지갑",
        "뷰티 > 스킨케어 > 에센스",
        "뷰티 > 스킨케어 > 크림",
        "스포츠 > 운동복 > 상의",
        "스포츠 > 운동복 > 하의",
        "스포츠 > 운동화 > 런닝화",
    ],
    "hmall": [
        "패션 > 남성패션 > 티셔츠",
        "패션 > 남성패션 > 셔츠",
        "패션 > 남성패션 > 니트/스웨터",
        "패션 > 남성패션 > 팬츠/진",
        "패션 > 남성패션 > 아우터",
        "패션 > 여성패션 > 원피스",
        "패션 > 여성패션 > 블라우스",
        "패션 > 여성패션 > 니트/스웨터",
        "패션 > 여성패션 > 팬츠",
        "패션 > 여성패션 > 아우터",
        "패션 > 슈즈 > 스니커즈",
        "패션 > 슈즈 > 구두/로퍼",
        "패션 > 슈즈 > 부츠",
        "패션잡화 > 가방 > 백팩",
        "패션잡화 > 가방 > 크로스백",
        "패션잡화 > 가방 > 토트백",
        "패션잡화 > 가방 > 숄더백",
        "패션잡화 > 가방 > 클러치/파우치",
        "패션잡화 > 가방 > 여행용 가방",
        "패션잡화 > 모자",
        "패션잡화 > 양말",
        "패션잡화 > 지갑",
        "뷰티 > 기초케어 > 에센스/세럼",
        "뷰티 > 기초케어 > 크림",
        "뷰티 > 선케어 > 선크림",
        "스포츠 > 스포츠의류 > 상의",
        "스포츠 > 스포츠의류 > 하의",
        "스포츠 > 스포츠슈즈 > 운동화",
    ],
    "ebay": [
        "Clothing, Shoes & Accessories > Men > Men's Shoes > Athletic Shoes",
        "Clothing, Shoes & Accessories > Men > Men's Shoes > Casual Shoes",
        "Clothing, Shoes & Accessories > Men > Men's Clothing > Shirts",
        "Clothing, Shoes & Accessories > Men > Men's Clothing > Pants",
        "Clothing, Shoes & Accessories > Men > Men's Clothing > Coats, Jackets & Vests",
        "Clothing, Shoes & Accessories > Women > Women's Shoes > Athletic Shoes",
        "Clothing, Shoes & Accessories > Women > Women's Clothing > Dresses",
        "Clothing, Shoes & Accessories > Women > Women's Bags & Handbags",
        "Health & Beauty > Skin Care > Moisturizers",
        "Health & Beauty > Skin Care > Serums",
    ],
    "lazada": [
        "Fashion > Men's Clothing > T-Shirts",
        "Fashion > Men's Clothing > Pants",
        "Fashion > Men's Shoes > Sneakers",
        "Fashion > Women's Clothing > Dresses",
        "Fashion > Women's Shoes > Sneakers",
        "Fashion > Bags > Backpacks",
        "Fashion > Bags > Crossbody Bags",
        "Health & Beauty > Skin Care > Essence",
    ],
    "qoo10": [
        "패션 > 남성의류 > 티셔츠",
        "패션 > 남성의류 > 팬츠",
        "패션 > 여성의류 > 원피스",
        "패션 > 신발 > 스니커즈",
        "패션 > 가방 > 백팩",
        "뷰티 > 스킨케어 > 에센스",
    ],
    "shopee": [
        "Men Clothes > T-Shirts",
        "Men Clothes > Pants",
        "Men Shoes > Sneakers",
        "Women Clothes > Dresses",
        "Women Shoes > Sneakers",
        "Women Bags > Backpacks",
        "Women Bags > Crossbody Bags",
        "Health & Beauty > Skin Care",
    ],
    "shopify": [
        "Apparel > Men > Tops",
        "Apparel > Men > Bottoms",
        "Apparel > Men > Outerwear",
        "Apparel > Women > Dresses",
        "Shoes > Men > Sneakers",
        "Shoes > Women > Sneakers",
        "Bags > Backpacks",
        "Beauty > Skin Care",
    ],
    "zoom": [
        "패션 > 남성의류 > 티셔츠",
        "패션 > 남성의류 > 팬츠",
        "패션 > 여성의류 > 원피스",
        "패션 > 신발 > 스니커즈",
        "패션 > 가방 > 백팩",
        "뷰티 > 스킨케어 > 에센스",
    ],
    "kream": [
        # 신발
        "신발 > 스니커즈 > 농구화",
        "신발 > 스니커즈 > 라이프스타일",
        "신발 > 스니커즈 > 러닝화",
        "신발 > 스니커즈 > 테니스/클래식",
        "신발 > 스니커즈 > 스케이트보드",
        "신발 > 스니커즈 > 하이탑",
        "신발 > 스포츠화",
        "신발 > 부츠",
        "신발 > 구두/로퍼",
        "신발 > 샌들/슬리퍼",
        # 의류
        "의류 > 상의 > 반팔 티셔츠",
        "의류 > 상의 > 긴팔 티셔츠",
        "의류 > 상의 > 후드 티셔츠",
        "의류 > 상의 > 맨투맨",
        "의류 > 상의 > 셔츠",
        "의류 > 상의 > 니트",
        "의류 > 아우터 > 자켓",
        "의류 > 아우터 > 패딩",
        "의류 > 아우터 > 코트",
        "의류 > 아우터 > 플리스",
        "의류 > 하의 > 팬츠",
        "의류 > 하의 > 청바지",
        "의류 > 하의 > 반바지",
        # 가방
        "가방 > 백팩",
        "가방 > 크로스백",
        "가방 > 토트백",
        "가방 > 숄더백",
        "가방 > 클러치/파우치",
        "가방 > 에코백",
        "가방 > 더플백",
        # 잡화
        "패션잡화 > 모자",
        "패션잡화 > 양말",
        "패션잡화 > 시계",
        "패션잡화 > 선글라스",
        "패션잡화 > 지갑",
        "패션잡화 > 벨트",
        "패션잡화 > 키링/참",
        "테크 > 이어폰/헤드폰",
        "테크 > 스피커",
    ],
}


class SambaCategoryService:
    def __init__(
        self,
        mapping_repo: SambaCategoryMappingRepository,
        tree_repo: SambaCategoryTreeRepository,
    ):
        self.mapping_repo = mapping_repo
        self.tree_repo = tree_repo

    # ==================== Category Mappings ====================

    async def list_mappings(
        self, skip: int = 0, limit: int = 50
    ) -> List[SambaCategoryMapping]:
        return await self.mapping_repo.list_async(
            skip=skip, limit=limit, order_by="-created_at"
        )

    async def create_mapping(
        self, data: Dict[str, Any]
    ) -> SambaCategoryMapping:
        return await self.mapping_repo.create_async(**data)

    async def update_mapping(
        self, mapping_id: str, data: Dict[str, Any]
    ) -> Optional[SambaCategoryMapping]:
        return await self.mapping_repo.update_async(mapping_id, **data)

    async def delete_mapping(self, mapping_id: str) -> bool:
        return await self.mapping_repo.delete_async(mapping_id)

    async def find_mapping(
        self, source_site: str, source_category: str
    ) -> Optional[SambaCategoryMapping]:
        return await self.mapping_repo.find_mapping(source_site, source_category)

    # ==================== Category Tree ====================

    async def get_category_tree(
        self, site_name: str
    ) -> Optional[SambaCategoryTree]:
        return await self.tree_repo.get_by_site(site_name)

    async def save_category_tree(
        self, site_name: str, data: Dict[str, Any]
    ) -> SambaCategoryTree:
        existing = await self.tree_repo.get_by_site(site_name)
        if existing:
            for key, value in data.items():
                if hasattr(existing, key):
                    setattr(existing, key, value)
            existing.updated_at = datetime.now(UTC)
            self.tree_repo.session.add(existing)
            await self.tree_repo.session.commit()
            await self.tree_repo.session.refresh(existing)
            return existing
        return await self.tree_repo.create_async(site_name=site_name, **data)

    async def delete_category_tree(self, site_name: str) -> bool:
        return await self.tree_repo.delete_by_site(site_name)

    # ==================== Category Suggestion ====================

    async def _get_market_categories(self, market: str) -> List[str]:
        """DB에서 마켓 카테고리를 조회하고, 없으면 하드코딩 fallback."""
        tree = await self.tree_repo.get_by_site(market)
        if tree and tree.cat1:
            return tree.cat1
        return MARKET_CATEGORIES.get(market, [])

    async def suggest_category(
        self, source_category: str, target_market: str
    ) -> List[str]:
        """카테고리 추천 — DB(API 동기화) 카테고리에서 키워드 매칭.

        1. DB에 동기화된 마켓 카테고리(cat1)에서 가중치 키워드 매칭
        2. cat2(코드맵)가 있으면 코드맵 키에서도 매칭 (실제 API 카테고리)
        3. AI fallback은 사용하지 않음 — 동기화된 카테고리만 사용
        """
        if not source_category:
            return []

        import re

        # 소싱처 ↔ 마켓 간 용어 차이 보완 (동의어 확장)
        SYNONYMS: Dict[str, List[str]] = {
            "아우터": ["재킷", "점퍼", "코트", "자켓", "바람막이", "패딩", "야상"],
            "상의": ["티셔츠", "셔츠", "니트", "맨투맨", "후드티", "블라우스"],
            "하의": ["바지", "팬츠", "슬랙스", "청바지", "레깅스", "치마"],
            "신발": ["스니커즈", "운동화", "구두", "부츠", "샌들", "슬리퍼"],
            "가방": ["백팩", "크로스백", "토트백", "숄더백", "클러치"],
        }

        raw_keywords = [
            k.strip()
            for k in re.split(r"[>/\s]+", source_category.lower())
            if len(k.strip()) > 1
        ]
        # 동의어 확장
        keywords = list(raw_keywords)
        for kw in raw_keywords:
            if kw in SYNONYMS:
                keywords.extend(SYNONYMS[kw])
        if not keywords:
            return []

        # DB에서 카테고리 목록 조회
        categories = await self._get_market_categories(target_market)
        if not categories:
            logger.warning("[카테고리 추천] %s: 동기화된 카테고리 없음 — 카테고리 동기화를 먼저 실행해주세요", target_market)
            return []

        # 가중치 키워드 매칭
        # 원본 키워드: 높은 가중치, 동의어: 낮은 가중치
        original_set = set(raw_keywords)
        scored = []
        for cat in categories:
            lower_cat = cat.lower()
            score = 0
            for kw in keywords:
                weight = 3 if kw in original_set else 1  # 원본=3, 동의어=1
                if kw in lower_cat:
                    score += weight * 2
                else:
                    segments = [s.strip() for s in re.split(r"[>/\s]+", lower_cat)]
                    for seg in segments:
                        if seg and (kw in seg or seg in kw):
                            score += weight
                            break
            if score > 0:
                scored.append((cat, score))

        scored.sort(key=lambda x: (-x[1], len(x[0])))
        return [cat for cat, _ in scored[:10]]

    async def _ai_suggest_categories(
        self, keyword: str, target_market: str
    ) -> List[str]:
        """AI로 마켓 카테고리 추천 (suggest_category fallback용)."""
        from backend.core.config import settings

        key = settings.anthropic_api_key
        if not key:
            # DB settings에서도 시도
            try:
                from backend.domain.samba.forbidden.repository import SambaSettingsRepository
                repo = SambaSettingsRepository(self.mapping_repo.session)
                row = await repo.find_by_async(key="claude")
                if row and isinstance(row.value, dict):
                    key = row.value.get("apiKey", "")
            except Exception:
                pass
        if not key:
            return []

        import anthropic

        market_label = {
            "smartstore": "네이버 스마트스토어",
            "coupang": "쿠팡",
            "gmarket": "G마켓",
            "auction": "옥션",
            "11st": "11번가",
            "ssg": "SSG(신세계)",
            "lotteon": "롯데ON",
            "lottehome": "롯데홈쇼핑",
            "gsshop": "GS샵",
            "homeand": "홈앤쇼핑",
            "hmall": "HMALL(현대)",
            "kream": "KREAM",
        }.get(target_market, target_market)

        prompt = f""""{keyword}" 검색어로 {market_label}에서 매칭되는 실제 카테고리 경로를 최대 10개 추천해주세요.

규칙:
1. {market_label}에 실제로 존재하는 카테고리만 사용하세요.
2. "대분류 > 중분류 > 소분류 > 세분류" 형태의 전체 경로로 작성하세요.
3. 관련도 높은 순서대로 나열하세요.
4. JSON 배열만 응답하세요 (설명 불필요).

예시 형식: ["뷰티 > 메이크업 > 블러셔", "뷰티 > 메이크업 > 치크"]"""

        try:
            client = anthropic.AsyncAnthropic(api_key=key)
            response = await client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=512,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
                if text.endswith("```"):
                    text = text[:-3].strip()
            result = json.loads(text)
            if isinstance(result, list):
                return [str(c) for c in result[:10]]
            return []
        except Exception as e:
            logger.warning("AI 카테고리 추천 실패 (%s): %s", target_market, e)
            return []

    async def get_market_category_list(self, market: str) -> List[str]:
        """마켓 카테고리 목록 조회 (DB 우선)."""
        return await self._get_market_categories(market)

    # ==================== Market Registration Check ====================

    async def check_market_registered(
        self,
        mapping_ids: List[str],
        market: str,
        session: "AsyncSession",
    ) -> int:
        """매핑 대상 카테고리의 상품이 해당 마켓에 등록(전송 완료)되었는지 확인.

        Returns: 등록된 상품 수
        """
        from sqlmodel import select
        from backend.domain.samba.collector.model import SambaCollectedProduct
        from backend.domain.samba.shipment.model import SambaShipment
        from backend.domain.samba.account.model import SambaMarketAccount

        # 1) 매핑 조회 → source_site + source_category 쌍 수집
        target_mappings = []
        for mid in mapping_ids:
            m = await self.mapping_repo.get_async(mid)
            if m:
                target_mappings.append((m.source_site, m.source_category))

        if not target_mappings:
            return 0

        # 2) 해당 카테고리의 상품 ID 수집
        stmt = select(SambaCollectedProduct.id, SambaCollectedProduct.source_site,
                       SambaCollectedProduct.category1, SambaCollectedProduct.category2,
                       SambaCollectedProduct.category3, SambaCollectedProduct.category4,
                       SambaCollectedProduct.category)
        result = await session.execute(stmt)
        product_ids: List[str] = []
        for row in result.all():
            pid, site = row[0], row[1]
            cats = [row[2], row[3], row[4], row[5]]
            cats = [c for c in cats if c]
            if not cats and row[6]:
                cats = [c.strip() for c in row[6].split(">") if c.strip()]
            leaf = " > ".join(cats)
            if (site, leaf) in target_mappings:
                product_ids.append(pid)

        if not product_ids:
            return 0

        # 3) 해당 마켓 계정 ID 조회
        stmt_acc = select(SambaMarketAccount.id).where(
            SambaMarketAccount.market_type == market
        )
        acc_result = await session.execute(stmt_acc)
        account_ids = [r[0] for r in acc_result.all()]
        if not account_ids:
            return 0

        # 4) 전송 완료된 shipment 확인
        stmt_ship = select(SambaShipment).where(
            SambaShipment.product_id.in_(product_ids),
            SambaShipment.status == "completed",
        )
        ship_result = await session.execute(stmt_ship)
        count = 0
        for ship in ship_result.scalars().all():
            if ship.target_account_ids:
                for aid in ship.target_account_ids:
                    if aid in account_ids:
                        count += 1
                        break
        return count

    # ==================== Market Category Seed ====================

    async def seed_market_categories(self) -> Dict[str, int]:
        """MARKET_CATEGORIES 하드코딩 데이터를 DB SambaCategoryTree에 저장.

        기존 DB 데이터가 있으면 병합 (중복 제거).
        Returns: { market: category_count } 딕셔너리
        """
        result: Dict[str, int] = {}
        for market, cats in MARKET_CATEGORIES.items():
            existing = await self.tree_repo.get_by_site(market)
            if existing:
                db_cats = existing.cat1 or []
                merged = list(dict.fromkeys(db_cats + cats))
                existing.cat1 = merged
                existing.updated_at = datetime.now(UTC)
                self.tree_repo.session.add(existing)
                result[market] = len(merged)
            else:
                await self.tree_repo.create_async(
                    site_name=market,
                    cat1=cats,
                )
                result[market] = len(cats)
        await self.tree_repo.session.commit()
        return result

    async def seed_market_via_ai(
        self, market_type: str, api_key: str
    ) -> Dict[str, Any]:
        """AI로 마켓의 전체 카테고리 목록을 생성하여 DB에 저장.

        계정/API 없는 마켓도 Claude가 실제 카테고리 체계를 알고 있으므로
        서비스 운영자가 미리 DB를 채워놓을 수 있다.
        """
        import anthropic

        market_label = {
            "smartstore": "네이버 스마트스토어",
            "coupang": "쿠팡",
            "gmarket": "G마켓",
            "auction": "옥션",
            "11st": "11번가",
            "ssg": "SSG(신세계몰)",
            "lotteon": "롯데ON",
            "lottehome": "롯데홈쇼핑",
            "gsshop": "GS샵",
            "homeand": "홈앤쇼핑",
            "hmall": "HMALL(현대홈쇼핑)",
            "kream": "KREAM",
            "ebay": "eBay Korea",
            "lazada": "Lazada",
            "qoo10": "Qoo10",
            "shopee": "Shopee",
        }.get(market_type, market_type)

        prompt = f"""{market_label}의 실제 상품 카테고리 전체 목록을 작성해주세요.

규칙:
1. 실제 {market_label} 셀러센터에서 상품 등록 시 선택하는 카테고리 체계를 따르세요.
2. "대분류 > 중분류 > 소분류 > 세분류" 형태의 전체 경로로 작성하세요.
3. 최하위(리프) 카테고리까지 모두 포함하세요.
4. 주요 카테고리를 빠짐없이 작성하세요 (패션, 뷰티, 식품, 가전, 생활, 스포츠 등).
5. 특히 패션(의류/신발/잡화)과 뷰티(스킨케어/메이크업/헤어/바디) 카테고리는 세분류까지 상세하게 작성하세요.
6. 최소 200개 이상의 리프 카테고리를 포함해주세요.
7. JSON 배열만 응답하세요.

예시: ["패션의류 > 여성의류 > 원피스", "뷰티 > 메이크업 > 블러셔", ...]"""

        client = anthropic.AsyncAnthropic(api_key=api_key)
        response = await client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=8192,
            messages=[{"role": "user", "content": prompt}],
        )

        text = response.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3].strip()

        categories = json.loads(text)
        if not isinstance(categories, list) or not categories:
            raise ValueError("AI 응답에서 카테고리 목록을 파싱할 수 없습니다")

        categories = [str(c) for c in categories if c]

        # DB에 병합 저장
        existing = await self.tree_repo.get_by_site(market_type)
        if existing:
            db_cats = existing.cat1 or []
            merged = list(dict.fromkeys(db_cats + categories))
            existing.cat1 = merged
            existing.updated_at = datetime.now(UTC)
            self.tree_repo.session.add(existing)
            count = len(merged)
        else:
            await self.tree_repo.create_async(site_name=market_type, cat1=categories)
            count = len(categories)
        await self.tree_repo.session.commit()

        logger.info("[AI 시드] %s: %d개 카테고리 생성/병합", market_type, count)
        return {"market": market_type, "count": count, "new": len(categories)}

    async def seed_all_markets_via_ai(self, api_key: str) -> Dict[str, Any]:
        """모든 마켓의 카테고리를 AI로 일괄 생성."""
        markets = list(MARKET_CATEGORIES.keys())
        results: Dict[str, Any] = {}
        for market in markets:
            try:
                result = await self.seed_market_via_ai(market, api_key)
                results[market] = {"ok": True, **result}
            except Exception as e:
                results[market] = {"ok": False, "error": str(e)}
                logger.warning("[AI 시드] %s 실패: %s", market, e)
        return results

    # ==================== Market Category Sync (API 연동) ====================

    async def _get_account(
        self, market_type: str, session: "AsyncSession"
    ) -> "SambaMarketAccount":
        """계정관리 테이블에서 마켓 계정 조회 (활성 계정 우선)."""
        from sqlmodel import select
        from backend.domain.samba.account.model import SambaMarketAccount

        stmt = (
            select(SambaMarketAccount)
            .where(SambaMarketAccount.market_type == market_type)
            .where(SambaMarketAccount.is_active.is_(True))
            .limit(1)
        )
        result = await session.execute(stmt)
        account = result.scalars().first()
        if not account:
            raise ValueError(
                f"{market_type} 계정이 등록되지 않았습니다. 계정관리에서 먼저 추가해주세요."
            )
        return account

    async def sync_market_from_api(
        self, market_type: str, session: "AsyncSession"
    ) -> Dict[str, Any]:
        """마켓 API에서 카테고리를 실시간 조회하여 DB에 저장.

        계정관리 테이블(SambaMarketAccount)에서 인증 정보를 직접 읽는다.
        """
        account = await self._get_account(market_type, session)
        categories: List[str] = []
        code_map: Optional[Dict[str, str]] = None

        # 모든 마켓이 (categories, code_map) 튜플 반환
        sync_methods = {
            "smartstore": self._sync_smartstore,
            "lotteon": self._sync_lotteon,
            "ssg": self._sync_ssg,
            "gsshop": self._sync_gsshop,
            "coupang": self._sync_coupang,
            "11st": self._sync_elevenst,
            "lottehome": self._sync_lottehome,
        }
        method = sync_methods.get(market_type)
        if not method:
            raise ValueError(f"API 동기화를 지원하지 않는 마켓: {market_type}")

        result = await method(account)
        if isinstance(result, tuple):
            categories, code_map = result
        else:
            categories = result

        if not categories:
            raise ValueError(f"{market_type} 카테고리 조회 결과가 비어있습니다. 계정 인증 정보를 확인해주세요.")

        # DB에 저장 (기존 데이터 교체)
        existing = await self.tree_repo.get_by_site(market_type)
        if existing:
            existing.cat1 = categories
            if code_map is not None:
                existing.cat2 = code_map
            existing.updated_at = datetime.now(UTC)
            self.tree_repo.session.add(existing)
        else:
            tree = await self.tree_repo.create_async(site_name=market_type, cat1=categories)
            if code_map is not None:
                tree.cat2 = code_map
                self.tree_repo.session.add(tree)
        await self.tree_repo.session.commit()

        logger.info("[카테고리 동기화] %s: %d개 카테고리 저장", market_type, len(categories))
        return {"count": len(categories), "updated_at": datetime.now(UTC).isoformat()}

    async def resolve_category_code(self, market_type: str, category_path: str) -> str:
        """경로 문자열 → 마켓 숫자 코드 변환. cat2에 저장된 코드맵 사용.

        매칭 우선순위:
        1. 정확 매칭
        2. 마지막 세그먼트 키워드 기반 퍼지 매칭 (leaf 카테고리 유사도)
        """
        tree = await self.tree_repo.get_by_site(market_type)
        if not tree or not tree.cat2:
            return ""
        code_map = tree.cat2
        # 1. 정확 매칭
        if category_path in code_map:
            return str(code_map[category_path])

        # 2. 키워드 기반 퍼지 매칭
        # 입력 경로의 세그먼트 추출 (예: "패션의류 > 남성의류 > 아우터/코트")
        input_segments = [s.strip() for s in category_path.split(">") if s.strip()]
        if not input_segments:
            return ""

        # 마지막 세그먼트의 키워드 추출 (슬래시 분리 포함)
        last_seg = input_segments[-1]
        input_keywords = set()
        for part in last_seg.replace("/", " ").replace(",", " ").split():
            if len(part) >= 2:
                input_keywords.add(part)
        # 상위 세그먼트 키워드도 추가 (낮은 가중치용)
        parent_keywords = set()
        for seg in input_segments[:-1]:
            for part in seg.replace("/", " ").replace(",", " ").split():
                if len(part) >= 2:
                    parent_keywords.add(part)

        if not input_keywords:
            return ""

        best_code = ""
        best_score = 0
        for path, code in code_map.items():
            path_segments = [s.strip() for s in path.split(">") if s.strip()]
            if not path_segments:
                continue
            path_last = path_segments[-1]
            path_keywords = set()
            for part in path_last.replace("/", " ").replace(",", " ").split():
                if len(part) >= 2:
                    path_keywords.add(part)

            # 마지막 세그먼트 키워드 겹침 점수
            overlap = len(input_keywords & path_keywords)
            if overlap == 0:
                continue
            score = overlap * 10

            # 상위 세그먼트 키워드 보너스
            path_all_keywords = set()
            for seg in path_segments[:-1]:
                for part in seg.replace("/", " ").replace(",", " ").split():
                    if len(part) >= 2:
                        path_all_keywords.add(part)
            parent_overlap = len(parent_keywords & path_all_keywords)
            score += parent_overlap * 3

            if score > best_score:
                best_score = score
                best_code = str(code)

        if best_code:
            logger.info("[카테고리 코드] 퍼지 매칭: '%s' → %s (score=%d)", category_path, best_code, best_score)
        return best_code

    async def sync_all_markets(self, session: "AsyncSession") -> Dict[str, Any]:
        """등록된 모든 마켓의 카테고리를 API에서 일괄 동기화.

        각 마켓별 60초 타임아웃. 계정 없는 마켓은 빠르게 스킵.
        """
        markets = ["smartstore", "coupang", "11st", "lotteon", "lottehome", "ssg", "gsshop"]
        results: Dict[str, Any] = {}
        for market in markets:
            try:
                result = await asyncio.wait_for(
                    self.sync_market_from_api(market, session),
                    timeout=60,
                )
                results[market] = {"ok": True, **result}
                logger.info("[카테고리 동기화] %s 완료: %d개", market, result.get("count", 0))
            except asyncio.TimeoutError:
                results[market] = {"ok": False, "error": "타임아웃 (60초 초과)"}
                logger.warning("[카테고리 동기화] %s 타임아웃", market)
            except Exception as e:
                results[market] = {"ok": False, "error": str(e)}
                logger.warning("[카테고리 동기화] %s 실패: %s", market, e)
        return results

    async def _sync_smartstore(self, account) -> tuple:
        """스마트스토어 카테고리 동기화 (Naver Commerce API). (카테고리목록, 코드맵) 반환."""
        from backend.domain.samba.proxy.smartstore import SmartStoreClient

        extra = account.additional_fields or {}
        client_id = extra.get("clientId") or account.api_key or ""
        client_secret = extra.get("clientSecret") or account.api_secret or ""
        if not client_id or not client_secret:
            raise ValueError("스마트스토어 clientId/clientSecret이 없습니다")

        client = SmartStoreClient(client_id, client_secret)
        raw = await client.get_categories(last_only=True)

        categories: List[str] = []
        code_map: Dict[str, str] = {}
        if isinstance(raw, list):
            for item in raw:
                whole = item.get("wholeCategoryName", "")
                cat_id = str(item.get("id", ""))
                if whole:
                    normalized = " > ".join(
                        seg.strip() for seg in whole.split(">") if seg.strip()
                    )
                    categories.append(normalized)
                    if cat_id:
                        code_map[normalized] = cat_id
        return categories, code_map if code_map else None

    async def _sync_coupang(self, account) -> tuple:
        """쿠팡 카테고리 동기화 (Wing API). (카테고리목록, 코드맵) 튜플 반환.

        쿠팡 API는 트리 구조로 반환하므로 평탄화하여 경로 문자열 + 코드맵 생성.
        """
        from backend.domain.samba.proxy.coupang import CoupangClient

        extra = account.additional_fields or {}
        client = CoupangClient(
            access_key=extra.get("accessKey") or account.api_key or "",
            secret_key=extra.get("secretKey") or account.api_secret or "",
            vendor_id=extra.get("vendorId") or account.seller_id or "",
        )
        raw = await client.get_categories()
        root = raw.get("data", raw) if isinstance(raw, dict) else {}
        if not isinstance(root, dict):
            return [], None

        # 트리 평탄화: 리프 노드의 경로 문자열 + 코드 추출
        categories: List[str] = []
        code_map: Dict[str, str] = {}

        def flatten(node: dict, path: str = "") -> None:
            code = node.get("displayItemCategoryCode", 0)
            name = node.get("name", "")
            if name == "ROOT":
                name = ""
            current = f"{path} > {name}" if path and name else (path or name)
            children = node.get("child", [])
            if not children and current and code:
                categories.append(current)
                code_map[current] = str(code)
            for c in children:
                flatten(c, current)

        flatten(root)
        return categories, code_map

    async def _sync_elevenst(self, account) -> tuple:
        """11번가 카테고리 동기화. (카테고리목록, {경로: 숫자코드}) 튜플 반환.

        11번가 API 응답은 ns2:category XML로 계층 구조를 반환한다.
        depth / dispNm / dispNo / parentDispNo 필드를 파싱하여
        전체 경로 문자열과 숫자 코드 매핑을 생성한다.
        """
        from xml.etree import ElementTree as ET

        import httpx

        url = "https://api.11st.co.kr/rest/cateservice/category"
        headers = {
            "openapikey": account.api_key or "",
            "Accept": "application/xml",
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, headers=headers)
            logger.info("[11번가] GET /cateservice/category → %s", resp.status_code)

        if not resp.is_success:
            raise ValueError(f"11번가 카테고리 API 에러: HTTP {resp.status_code}")

        # XML 파싱 (네임스페이스 제거)
        xml_text = resp.text
        # 네임스페이스 프리픽스 제거하여 파싱 단순화
        xml_text = xml_text.replace("ns2:", "")
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            logger.error("[11번가] 카테고리 XML 파싱 실패")
            return [], {}

        # dispNo → dispNm 매핑 + parentDispNo 관계 구축
        node_map: Dict[str, str] = {}  # dispNo → dispNm
        parent_map: Dict[str, str] = {}  # dispNo → parentDispNo
        leaf_nodes: list = []  # leaf 카테고리 dispNo 목록

        for cat in root.findall("category"):
            disp_no = (cat.findtext("dispNo") or "").strip()
            disp_nm = (cat.findtext("dispNm") or "").strip()
            parent_no = (cat.findtext("parentDispNo") or "0").strip()
            is_leaf = (cat.findtext("leafYn") or "N").strip()

            if disp_no and disp_nm:
                node_map[disp_no] = disp_nm
                parent_map[disp_no] = parent_no
                if is_leaf == "Y":
                    leaf_nodes.append(disp_no)

        # 경로 생성 함수
        def build_path(disp_no: str) -> str:
            parts = []
            current = disp_no
            while current and current != "0" and current in node_map:
                parts.append(node_map[current])
                current = parent_map.get(current, "0")
            parts.reverse()
            return " > ".join(parts)

        # leaf 카테고리만 경로 생성 (등록 가능한 최하위 카테고리)
        categories = []
        code_map: Dict[str, str] = {}
        for disp_no in leaf_nodes:
            path = build_path(disp_no)
            if path:
                categories.append(path)
                code_map[path] = disp_no

        logger.info("[11번가] 카테고리 파싱 완료: %d개 (leaf), 코드맵 %d개", len(categories), len(code_map))
        return categories, code_map

    async def _sync_lotteon(self, account) -> tuple:
        """롯데ON 카테고리 동기화. (카테고리목록, 코드맵) 반환."""
        from backend.domain.samba.proxy.lotteon import LotteonClient

        extra = account.additional_fields or {}
        api_key = extra.get("apiKey") or account.api_key or ""
        if not api_key:
            raise ValueError("롯데ON API Key가 없습니다")
        client = LotteonClient(api_key=api_key)

        # 롯데ON은 페이지당 100건, 전체 뎁스 반복 조회
        node_map: Dict[str, str] = {}  # std_cat_id → std_cat_nm
        parent_map: Dict[str, str] = {}  # std_cat_id → upr_std_cat_id
        leaf_ids: List[str] = []

        for depth in ["1", "2", "3", "4"]:
            try:
                raw = await client.get_categories(depth=depth)
                items = raw.get("itemList", [])
                if not items:
                    break
                for item in items:
                    d = item.get("data", item)
                    cat_id = d.get("std_cat_id", "")
                    cat_nm = d.get("std_cat_nm", "")
                    parent_id = d.get("upr_std_cat_id", "0")
                    if cat_id and cat_nm:
                        node_map[cat_id] = cat_nm
                        parent_map[cat_id] = parent_id
                        if depth == "4" or d.get("leaf_yn") == "Y":
                            leaf_ids.append(cat_id)
            except Exception:
                break

        # leaf가 없으면 가장 깊은 뎁스를 leaf로 사용
        if not leaf_ids:
            leaf_ids = list(node_map.keys())

        # 경로 생성
        def build_path(cat_id: str) -> str:
            parts = []
            current = cat_id
            while current and current != "0" and current in node_map:
                parts.append(node_map[current])
                current = parent_map.get(current, "0")
            parts.reverse()
            return " > ".join(parts)

        categories: List[str] = []
        code_map: Dict[str, str] = {}
        for cat_id in leaf_ids:
            path = build_path(cat_id)
            if path:
                categories.append(path)
                code_map[path] = cat_id

        return categories, code_map if code_map else None

    async def _sync_lottehome(self, account) -> tuple:
        """롯데홈쇼핑 카테고리 동기화. (카테고리목록, 코드맵) 반환."""
        from backend.domain.samba.proxy.lottehome import LotteHomeClient

        extra = account.additional_fields or {}
        user_id = extra.get("userId") or account.seller_id or ""
        client = LotteHomeClient(
            user_id=user_id,
            password=extra.get("password") or account.api_secret or "",
            agnc_no=extra.get("agncNo") or user_id,  # 로그인ID = 업체번호 동일
            env=extra.get("env") or "prod",
        )
        raw = await client.search_categories()
        categories: List[str] = []
        code_map: Dict[str, str] = {}
        data = raw.get("data", {}) if isinstance(raw, dict) else {}
        items = data if isinstance(data, list) else []
        if isinstance(data, dict):
            for key in ("DispCatList", "dispCatList", "category", "list", "items"):
                val = data.get(key)
                if isinstance(val, list):
                    items = val
                    break
        for item in items:
            if isinstance(item, dict):
                name = item.get("dispCatNm") or item.get("categoryName") or item.get("name", "")
                cat_id = str(item.get("dispCatNo") or item.get("categoryNo") or item.get("id", ""))
                if name:
                    categories.append(name)
                    if cat_id:
                        code_map[name] = cat_id
            elif isinstance(item, str) and item:
                categories.append(item)
        return categories, code_map if code_map else None

    async def _sync_ssg(self, account) -> tuple:
        """SSG 카테고리 동기화. (카테고리목록, 코드맵) 반환."""
        from backend.domain.samba.proxy.ssg import SSGClient

        extra = account.additional_fields or {}
        api_key = extra.get("apiKey") or account.api_key or ""
        if not api_key:
            raise ValueError("SSG API Key가 없습니다")
        client = SSGClient(api_key=api_key)
        raw = await client.get_categories()
        categories: List[str] = []
        code_map: Dict[str, str] = {}
        items = raw.get("data", raw) if isinstance(raw, dict) else raw
        if isinstance(items, list):
            for item in items:
                name = item.get("wholeCategoryName") or item.get("stdCtgNm") or item.get("categoryName") or item.get("name", "")
                cat_id = str(item.get("stdCtgId") or item.get("categoryId") or item.get("id", ""))
                if name:
                    normalized = " > ".join(
                        seg.strip() for seg in name.split(">") if seg.strip()
                    )
                    categories.append(normalized)
                    if cat_id:
                        code_map[normalized] = cat_id
        return categories, code_map if code_map else None

    async def _sync_gsshop(self, account) -> tuple:
        """GS샵 카테고리 동기화. (카테고리목록, 코드맵) 반환."""
        from backend.domain.samba.proxy.gsshop import GsShopClient

        extra = account.additional_fields or {}
        env = extra.get("env") or "prod"
        aes_key = extra.get("aesKey") or (
            extra.get("apiKeyProd") if env == "prod" else extra.get("apiKeyDev")
        ) or account.api_key or ""
        if not aes_key:
            raise ValueError("GS샵 AES Key가 없습니다")
        client = GsShopClient(
            sup_cd=extra.get("supCd") or account.seller_id or "",
            aes_key=aes_key,
            sub_sup_cd=extra.get("subSupCd") or "",
            env=env,
        )
        raw = await client.get_product_categories()
        categories: List[str] = []
        code_map: Dict[str, str] = {}
        # GS샵 응답: data.resultList[{lrgClsNm, midClsNm, smlClsNm, dtlClsNm, dtlClsCd}]
        data = raw.get("data", raw) if isinstance(raw, dict) else raw
        items = data.get("resultList", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
        for item in items:
            if not isinstance(item, dict):
                continue
            parts = [
                item.get("lrgClsNm", ""),
                item.get("midClsNm", ""),
                item.get("smlClsNm", ""),
                item.get("dtlClsNm", ""),
            ]
            path = " > ".join(p for p in parts if p)
            cat_id = item.get("dtlClsCd") or item.get("smlClsCd") or ""
            if path:
                categories.append(path)
                if cat_id:
                    code_map[path] = str(cat_id)
        return categories, code_map if code_map else None

    # ==================== AI Category Suggestion ====================

    async def ai_suggest_category(
        self,
        source_site: str,
        source_category: str,
        sample_products: List[str],
        target_markets: Optional[List[str]] = None,
        api_key: Optional[str] = None,
    ) -> Dict[str, str]:
        """Claude API를 사용하여 소싱 카테고리를 마켓별 카테고리로 매핑 추천.

        DB에 저장된 마켓 카테고리를 우선 사용하고, 없으면 하드코딩 fallback.
        """
        from backend.core.config import settings

        key = api_key or settings.anthropic_api_key
        if not key:
            raise ValueError("ANTHROPIC_API_KEY가 설정되지 않았습니다")

        import anthropic

        markets = target_markets or list(MARKET_CATEGORIES.keys())
        # DB 우선 조회 후 하드코딩 fallback
        market_cats: Dict[str, List[str]] = {}
        for m in markets:
            cats = await self._get_market_categories(m)
            if cats:
                market_cats[m] = cats

        if not market_cats:
            return {}

        # 프롬프트 구성
        market_list_str = "\n".join(
            f"- {market}: {json.dumps(cats, ensure_ascii=False)}"
            for market, cats in market_cats.items()
        )
        sample_str = ", ".join(sample_products[:5]) if sample_products else "(없음)"

        prompt = f"""소싱 상품의 카테고리를 각 판매 마켓의 카테고리에 매핑해주세요.

[소싱 정보]
- 사이트: {source_site}
- 카테고리: {source_category}
- 대표 상품명: {sample_str}

[마켓별 카테고리 목록 (참고용)]
{market_list_str}

규칙:
1. 각 마켓에서 가장 적절한 카테고리를 정확히 1개만 선택하세요.
2. 위 목록에 정확히 일치하는 카테고리가 있으면 그것을 선택하세요.
3. 정확히 일치하는 카테고리가 없으면 상품명과 소싱 카테고리를 분석하여 해당 마켓에서 가장 적절한 카테고리 경로를 직접 생성하세요. 실제 마켓에서 사용하는 카테고리 체계를 따르세요.
4. 절대로 빈 문자열로 응답하지 마세요. 모든 마켓에 반드시 카테고리를 매핑해야 합니다.
5. 최하위 카테고리까지 매핑이 어려우면 가장 가까운 상위 카테고리를 사용하세요.

JSON만 응답하세요 (설명 불필요):
{json.dumps({m: "" for m in market_cats}, ensure_ascii=False)}"""

        client = anthropic.AsyncAnthropic(api_key=key)

        try:
            response = await client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
            )

            # 응답에서 JSON 추출
            text = response.content[0].text.strip()
            # ```json ... ``` 블록 제거
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
                if text.endswith("```"):
                    text = text[:-3].strip()

            result = json.loads(text)

            # 응답 검증: 마켓 키가 유효하고 값이 있으면 수용
            # AI가 목록 외 카테고리를 생성할 수 있으므로 엄격 검증하지 않음
            validated: Dict[str, str] = {}
            for market, suggested in result.items():
                if market in market_cats and suggested:
                    validated[market] = suggested
                    if suggested not in market_cats[market]:
                        logger.info(
                            "AI가 %s에 목록 외 카테고리 '%s' 생성",
                            market, suggested,
                        )

            return validated

        except json.JSONDecodeError as e:
            logger.error("AI 응답 JSON 파싱 실패: %s", e)
            raise ValueError(f"AI 응답 파싱 실패: {e}") from e
        except anthropic.APIError as e:
            logger.error("Claude API 오류: %s", e)
            raise ValueError(f"Claude API 오류: {e}") from e

    # ==================== Bulk AI Mapping ====================

    async def bulk_ai_mapping(
        self, api_key: str, session: "AsyncSession"
    ) -> Dict[str, Any]:
        """미매핑 카테고리 자동 매핑 + 기존 매핑 누락 마켓 보충.

        1) 수집 상품 전체에서 고유 (site, leaf_category) 추출
        2) 기존 매핑 전체 조회
        3-A) 미매핑 → AI → 새 매핑 생성
        3-B) 기존 매핑 중 MARKET_CATEGORIES 키 빠진 것 → AI → 매핑 업데이트
        """
        from sqlmodel import select
        from backend.domain.samba.collector.model import SambaCollectedProduct

        all_market_keys = set(MARKET_CATEGORIES.keys())

        # 1) 수집 상품에서 고유 (site, leaf_category, 대표 상품명) 추출
        stmt = select(SambaCollectedProduct)
        result = await session.execute(stmt)
        products = list(result.scalars().all())

        # (site, leaf_path) → 대표 상품명 목록
        cat_samples: Dict[tuple, List[str]] = {}
        for p in products:
            site = p.source_site or ""
            if not site:
                continue
            cats = [p.category1, p.category2, p.category3, p.category4]
            cats = [c for c in cats if c]
            if not cats and p.category:
                cats = [c.strip() for c in p.category.split(">") if c.strip()]
            if not cats:
                continue
            leaf_path = " > ".join(cats)
            key = (site, leaf_path)
            if key not in cat_samples:
                cat_samples[key] = []
            if len(cat_samples[key]) < 5:
                cat_samples[key].append(p.name)

        if not cat_samples:
            return {"mapped": 0, "updated": 0, "skipped": 0, "errors": []}

        # 2) 기존 매핑 전체 조회
        existing_mappings = await self.mapping_repo.list_all()
        existing_map: Dict[tuple, SambaCategoryMapping] = {}
        for m in existing_mappings:
            existing_map[(m.source_site, m.source_category)] = m

        mapped = 0
        updated = 0
        skipped = 0
        errors: List[str] = []

        for (site, leaf_path), samples in cat_samples.items():
            existing = existing_map.get((site, leaf_path))

            if existing:
                # 3-B) 기존 매핑에서 누락 마켓 확인
                current_targets = existing.target_mappings or {}
                missing_markets = all_market_keys - set(current_targets.keys())
                if not missing_markets:
                    skipped += 1
                    continue

                # 누락 마켓만 AI 추천
                try:
                    ai_result = await self.ai_suggest_category(
                        source_site=site,
                        source_category=leaf_path,
                        sample_products=samples,
                        target_markets=list(missing_markets),
                        api_key=api_key,
                    )
                    # 기존 매핑에 추가
                    new_targets = {**current_targets}
                    for market, cat in ai_result.items():
                        if cat:
                            new_targets[market] = cat
                    await self.update_mapping(existing.id, {"target_mappings": new_targets})
                    updated += 1
                except Exception as e:
                    errors.append(f"[보충] {site} > {leaf_path}: {e}")
            else:
                # 3-A) 미매핑 → AI → 새 매핑 생성
                try:
                    ai_result = await self.ai_suggest_category(
                        source_site=site,
                        source_category=leaf_path,
                        sample_products=samples,
                        api_key=api_key,
                    )
                    target_mappings = {m: c for m, c in ai_result.items() if c}
                    if target_mappings:
                        await self.create_mapping({
                            "source_site": site,
                            "source_category": leaf_path,
                            "target_mappings": target_mappings,
                        })
                        mapped += 1
                    else:
                        skipped += 1
                except Exception as e:
                    errors.append(f"[신규] {site} > {leaf_path}: {e}")

        return {"mapped": mapped, "updated": updated, "skipped": skipped, "errors": errors}
