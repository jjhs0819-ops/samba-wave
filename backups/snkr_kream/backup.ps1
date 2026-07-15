# 스니덩크↔크림 매칭 매핑 일일 백업.
# samba_collected_product(SNKRDUNK) 의 resell_matches.kream 매핑을 jsonl 로 덤프.
# 목적: 매칭상품이 삭제돼도 스니덩 id 를 잃지 않게 사전 보관 → 반자동 복구(restore) 재료.
# 실행: Windows 작업 스케줄러 매일 1회 (pwsh backup.ps1). 백엔드 재빌드 불필요.

$ErrorActionPreference = "Stop"
$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$date = Get-Date -Format "yyyy-MM-dd"
$out = Join-Path $dir "snkr_kream_$date.jsonl"

# 매핑 재생성에 필요한 최소 필드만 (스니덩id·크림id·이름·품번·이미지·타입)
$sql = @"
SELECT json_build_object(
  'snkr_id', site_product_id,
  'kream_id', resell_matches->'kream'->>'product_id',
  'name', name,
  'kream_name_ko', resell_matches->'kream'->>'name_ko',
  'style_code', style_code,
  'snkr_type', extra_data->>'snkr_type',
  'image', images->>0
)
FROM samba_collected_product
WHERE source_site='SNKRDUNK' AND resell_matches->'kream'->>'product_id' <> ''
"@

# 컨테이너 안에서 UTF-8 로 파일 생성 후 host 로 복사 (콘솔 인코딩 깨짐 방지)
$one = ($sql -replace "`r?`n", " ")
docker exec local-postgres-1 sh -c "psql -U samba -d samba -t -A -c `"$one`" > /tmp/snkr_kream.jsonl"
docker cp local-postgres-1:/tmp/snkr_kream.jsonl "$out"

# 검증 — 라인수 비정상(대량 손실)이면 실패 처리
$cnt = (Get-Content $out | Where-Object { $_.Trim() -ne "" } | Measure-Object).Count
if ($cnt -lt 1000) { Write-Error "백업 라인수 비정상($cnt) — 중단" }

# 최근 14개만 보관, 나머지 삭제
Get-ChildItem $dir -Filter "snkr_kream_*.jsonl" |
  Sort-Object Name -Descending | Select-Object -Skip 14 | Remove-Item -Force

Write-Host "백업 완료: $out ($cnt 건)"
