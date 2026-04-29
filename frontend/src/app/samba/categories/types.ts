import type { SambaCollectedProduct } from '@/lib/samba/api/commerce'

// 카테고리 계층 구조 타입
export interface CatLevel {
  name: string
  children: Record<string, CatLevel>
  products: SambaCollectedProduct[]
}

// 매핑 현황 행 타입
export interface MappingRow {
  id: string
  source_site: string
  source_category: string
  target_mappings: Record<string, string>
}
