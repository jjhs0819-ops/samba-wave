export const STATUS_MAP: Record<string, { label: string; bg: string; text: string }> = {
  pending: { label: '주문접수', bg: 'rgba(255,211,61,0.15)', text: '#FFD93D' },
  preparing: { label: '상품준비중', bg: 'rgba(135,206,250,0.15)', text: '#87CEFA' },
  wait_ship: { label: '배송대기중', bg: 'rgba(100,149,237,0.15)', text: '#6495ED' },
  arrived: { label: '상품도착', bg: 'rgba(72,209,204,0.15)', text: '#48D1CC' },
  ship_failed: { label: '송장전송실패', bg: 'rgba(255,50,50,0.2)', text: '#FF3232' },
  shipping: { label: '국내배송중', bg: 'rgba(76,154,255,0.15)', text: '#4C9AFF' },
  delivered: { label: '배송완료', bg: 'rgba(81,207,102,0.15)', text: '#51CF66' },
  cancelling: { label: '취소중', bg: 'rgba(255,165,0,0.15)', text: '#FFA500' },
  returning: { label: '반품중', bg: 'rgba(200,100,200,0.15)', text: '#CC5DE8' },
  exchanging: { label: '교환중', bg: 'rgba(255,182,193,0.15)', text: '#FFB6C1' },
  cancel_requested: { label: '취소요청', bg: 'rgba(255,80,80,0.2)', text: '#FF5050' },
  cancel_reject_pending: { label: '취소거부(수동)', bg: 'rgba(139,92,246,0.2)', text: '#8B5CF6' },
  return_requested: { label: '반품요청', bg: 'rgba(200,100,200,0.2)', text: '#CC5DE8' },
  cancelled: { label: '취소완료', bg: 'rgba(255,107,107,0.15)', text: '#FF6B6B' },
  returned: { label: '반품완료', bg: 'rgba(180,80,180,0.15)', text: '#B44EB4' },
  exchanged: { label: '교환완료', bg: 'rgba(144,238,144,0.15)', text: '#90EE90' },
  return_completed: { label: '회수확정', bg: 'rgba(160,60,160,0.15)', text: '#A03CA0' },
  undeliverable: { label: '발송불가', bg: 'rgba(217,119,6,0.15)', text: '#F59E0B' },
}

// [2026-09-01] 주문상태 드롭다운 전용 색 — 불투명 배경 + 확실히 대비되는 글자색.
// STATUS_MAP 의 bg(rgba 0.15)는 너무 옅어 셀렉트 배경으로 못 쓰므로 별도 정의 (STATUS_MAP 은 손대지 않음).
// 밝은 배경엔 #1a1a1a, 어두운 배경엔 #fff — 라이트/다크 테마 무관하게 읽히도록 고정값 사용.
export const STATUS_SELECT_COLORS: Record<string, { bg: string; fg: string }> = {
  pending: { bg: '#FCC419', fg: '#1a1a1a' },               // 주문접수 — 노랑
  preparing: { bg: '#74C0FC', fg: '#1a1a1a' },             // 상품준비중 — 하늘
  wait_ship: { bg: '#4263EB', fg: '#fff' },                // 배송대기중 — 인디고
  arrived: { bg: '#15AABF', fg: '#fff' },                  // 상품도착 — 시안
  ship_failed: { bg: '#E03131', fg: '#fff' },              // 송장전송실패 — 빨강 (기존 하드코딩 흡수)
  shipping: { bg: '#1971C2', fg: '#fff' },                 // 국내배송중 — 파랑
  delivered: { bg: '#2F9E44', fg: '#fff' },                // 배송완료 — 초록
  cancelling: { bg: '#F76707', fg: '#fff' },               // 취소중 — 주황
  returning: { bg: '#AE3EC9', fg: '#fff' },                // 반품중 — 자주
  exchanging: { bg: '#F783AC', fg: '#1a1a1a' },            // 교환중 — 연분홍
  cancel_requested: { bg: '#A61E4D', fg: '#fff' },         // 취소요청 — 진한 자홍
  cancel_reject_pending: { bg: '#7048E8', fg: '#fff' },    // 취소거부(수동) — 보라
  return_requested: { bg: '#862E9C', fg: '#fff' },         // 반품요청 — 진보라
  cancelled: { bg: '#FFA8A8', fg: '#1a1a1a' },             // 취소완료 — 연한 빨강
  returned: { bg: '#E599F7', fg: '#1a1a1a' },              // 반품완료 — 연한 자주
  exchanged: { bg: '#8CE99A', fg: '#1a1a1a' },             // 교환완료 — 연초록
  return_completed: { bg: '#087F5B', fg: '#fff' },         // 회수확정 — 진한 청록
  undeliverable: { bg: '#795548', fg: '#fff' },            // 발송불가 — 갈색
}

export const SHIPPING_COMPANIES = ['CJ대한통운', '우진택배', '롯데택배', '로젠택배', '우체국택배', '경동택배', '한진택배', '일양로지스', '천일택배', '허브넷로지스틱스', '시리박스', '딜리박스', 'DHL', 'Rincos', 'Korea Post', '직접배송', '기타']

// [2026-07-02] 크림 해외송장용 — 일본 택배사 (input+datalist라 직접입력도 가능)
export const OVERSEAS_SHIPPING_COMPANIES = ['ヤマト運輸 야마토', '佐川急便 사가와', '日本郵便 일본우편', '西濃運輸 세이노', '福山通運 후쿠야마', 'EMS', 'DHL', 'FedEx', 'UPS', 'SF Express']

export const ACTION_BUTTONS = [
  { key: 'no_price', label: '가격X', activeColor: '#DC2626' },
  { key: 'no_stock', label: '재고X', activeColor: '#CA8A04' },
  { key: 'direct', label: '직배', activeColor: '#2563EB' },
  { key: 'kkadaegi', label: '까대기', activeColor: '#D97706' },
  { key: 'gift', label: '선물', activeColor: '#059669' },
  { key: 'staff_a', label: '직원A', activeColor: '#7C3AED' },
  { key: 'staff_b', label: '직원B', activeColor: '#DB2777' },
] as const
