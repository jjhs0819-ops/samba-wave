import { useEffect, useRef, useState } from 'react'
import { proxyApi } from '@/lib/samba/api/commerce'
import type { TagPreview, TagPreviewCost } from '../components/TagPreviewModal'

// AI 도구 관련 상태(태그 미리보기 / 이미지 변환 / 작업 진행 모달 / AI 비용 추적)를
// 한 곳에 묶어 관리하는 커스텀 훅.
// - 외부 비즈니스 로직(다른 도메인 state에 의존하는 핸들러)은 page.tsx에 그대로 둔다.
// - 본 훅은 setter를 함께 반환하여 page.tsx와 자식 컴포넌트가 그대로 사용 가능.
export type AiUsage = {
  calls: number
  tokens: number
  cost: number
  date: string
}

export type AiImgScope = {
  thumbnail: boolean
  additional: boolean
  detail: boolean
}

export type AiPreset = {
  key: string
  label: string
  desc: string
  image: string | null
}

export default function useAiTools() {
  // AI 비용 추적
  const [lastAiUsage, setLastAiUsage] = useState<AiUsage | null>(null)

  // AI 태그 미리보기 모달
  const [showTagPreview, setShowTagPreview] = useState(false)
  const [tagPreviews, setTagPreviews] = useState<TagPreview[]>([])
  const [tagPreviewCost, setTagPreviewCost] = useState<TagPreviewCost | null>(null)
  const [tagPreviewLoading, setTagPreviewLoading] = useState(false)
  const [removedTags, setRemovedTags] = useState<string[]>([])

  // AI 이미지 변환
  const [aiImgScope, setAiImgScope] = useState<AiImgScope>({ thumbnail: true, additional: true, detail: false })
  const [aiImgMode, setAiImgMode] = useState('background')
  const [aiModelPreset, setAiModelPreset] = useState('auto')
  const [aiImgTransforming, setAiImgTransforming] = useState(false)
  const [aiPresetList, setAiPresetList] = useState<AiPreset[]>([])

  // AI 작업 진행 모달
  const [aiJobModal, setAiJobModal] = useState(false)
  const [aiJobTitle, setAiJobTitle] = useState('')
  const [aiJobLogs, setAiJobLogs] = useState<string[]>([])
  const [aiJobDone, setAiJobDone] = useState(false)
  const aiJobAbortRef = useRef(false)

  // 마운트 시 AI 프리셋 목록 로드 (기존 page.tsx 동작과 동일)
  useEffect(() => {
    proxyApi
      .listPresets()
      .then((res) => {
        if (res.success) setAiPresetList(res.presets)
      })
      .catch(() => {})
  }, [])

  return {
    // AI 비용
    lastAiUsage,
    setLastAiUsage,
    // 태그 미리보기
    showTagPreview,
    setShowTagPreview,
    tagPreviews,
    setTagPreviews,
    tagPreviewCost,
    setTagPreviewCost,
    tagPreviewLoading,
    setTagPreviewLoading,
    removedTags,
    setRemovedTags,
    // 이미지 변환
    aiImgScope,
    setAiImgScope,
    aiImgMode,
    setAiImgMode,
    aiModelPreset,
    setAiModelPreset,
    aiImgTransforming,
    setAiImgTransforming,
    aiPresetList,
    setAiPresetList,
    // 작업 진행 모달
    aiJobModal,
    setAiJobModal,
    aiJobTitle,
    setAiJobTitle,
    aiJobLogs,
    setAiJobLogs,
    aiJobDone,
    setAiJobDone,
    aiJobAbortRef,
  }
}
