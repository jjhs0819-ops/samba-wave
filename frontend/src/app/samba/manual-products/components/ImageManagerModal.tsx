'use client'

import { useState } from 'react'

interface Props {
  images: string[]
  detailImages: string[]
  onSave: (images: string[], detailImages: string[]) => void
  onClose: () => void
}

type Tab = 'main' | 'extra' | 'detail'

const INPUT = 'flex-1 px-2.5 py-1.5 bg-[#0A0A0A] border border-[#1A1A1A] rounded text-sm text-[#E5E5E5] placeholder-[#444] focus:outline-none focus:border-[#FF8C00]'

export default function ImageManagerModal({ images, detailImages, onSave, onClose }: Props) {
  const [tab, setTab] = useState<Tab>('main')
  const [imgs, setImgs] = useState<string[]>(images)
  const [details, setDetails] = useState<string[]>(detailImages)
  const [urlInput, setUrlInput] = useState('')
  const [mainInput, setMainInput] = useState(images[0] ?? '')

  const extraImgs = imgs.slice(1)

  const setMainImg = (url: string) => {
    if (!url.trim()) return
    setImgs(prev => [url.trim(), ...prev.slice(1)])
  }

  const addExtra = (url: string) => {
    if (!url.trim()) return
    setImgs(prev => [...prev, url.trim()])
    setUrlInput('')
  }

  const removeExtra = (idx: number) =>
    setImgs(prev => prev.filter((_, i) => i !== idx + 1))

  const moveExtra = (idx: number, dir: -1 | 1) => {
    const arr = [...imgs]
    const from = idx + 1
    const to = from + dir
    if (to < 1 || to >= arr.length) return
    ;[arr[from], arr[to]] = [arr[to], arr[from]]
    setImgs(arr)
  }

  const addDetail = (url: string) => {
    if (!url.trim()) return
    setDetails(prev => [...prev, url.trim()])
    setUrlInput('')
  }

  const removeDetail = (idx: number) =>
    setDetails(prev => prev.filter((_, i) => i !== idx))

  const moveDetail = (idx: number, dir: -1 | 1) => {
    const arr = [...details]
    const to = idx + dir
    if (to < 0 || to >= arr.length) return
    ;[arr[idx], arr[to]] = [arr[to], arr[idx]]
    setDetails(arr)
  }

  const handleSave = () => {
    onSave(imgs.filter(Boolean), details.filter(Boolean))
    onClose()
  }

  const TAB_LABELS: { key: Tab; label: string }[] = [
    { key: 'main', label: '대표이미지' },
    { key: 'extra', label: `추가이미지 (${extraImgs.length})` },
    { key: 'detail', label: `상세이미지 (${details.length})` },
  ]

  return (
    <div className='fixed inset-0 bg-black/80 z-50 flex items-center justify-center'>
      <div className='bg-[#111] border border-[#1A1A1A] rounded-lg w-full max-w-xl max-h-[85vh] flex flex-col'>

        <div className='flex justify-between items-center px-4 py-3 border-b border-[#1A1A1A]'>
          <h3 className='text-sm font-semibold text-[#E5E5E5]'>이미지 관리</h3>
          <button onClick={onClose} className='text-[#666] hover:text-[#E5E5E5] text-xl leading-none'>×</button>
        </div>

        <div className='flex border-b border-[#1A1A1A] px-4'>
          {TAB_LABELS.map(t => (
            <button
              key={t.key}
              onClick={() => { setTab(t.key); setUrlInput('') }}
              className={`px-3 py-2.5 text-xs font-medium border-b-2 -mb-px transition-colors ${
                tab === t.key
                  ? 'border-[#FF8C00] text-[#FF8C00]'
                  : 'border-transparent text-[#666] hover:text-[#999]'
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>

        <div className='flex-1 overflow-y-auto p-4'>

          {tab === 'main' && (
            <div className='space-y-3'>
              {imgs[0] ? (
                <img src={imgs[0]} alt='' className='w-32 h-32 object-cover rounded border border-[#2D2D2D] mx-auto block' />
              ) : (
                <div className='w-32 h-32 rounded border border-[#2D2D2D] mx-auto flex items-center justify-center bg-[#0A0A0A]'>
                  <span className='text-[#444] text-xs'>미리보기</span>
                </div>
              )}
              <div>
                <label className='text-xs text-[#666] block mb-1'>대표이미지 URL</label>
                <div className='flex gap-2'>
                  <input
                    className={INPUT}
                    value={mainInput}
                    onChange={e => setMainInput(e.target.value)}
                    placeholder='https://...'
                  />
                  <button
                    onClick={() => setMainImg(mainInput)}
                    className='px-3 py-1.5 bg-[#FF8C00] text-white text-xs rounded hover:bg-[#E07B00]'
                  >
                    변경
                  </button>
                </div>
              </div>
            </div>
          )}

          {tab === 'extra' && (
            <div className='space-y-2'>
              <div className='flex gap-2 mb-3'>
                <input
                  className={INPUT}
                  value={urlInput}
                  onChange={e => setUrlInput(e.target.value)}
                  onKeyDown={e => { if (e.key === 'Enter') addExtra(urlInput) }}
                  placeholder='추가이미지 URL 입력'
                />
                <button onClick={() => addExtra(urlInput)} className='px-3 py-1.5 bg-[#FF8C00] text-white text-xs rounded hover:bg-[#E07B00]'>추가</button>
              </div>
              {extraImgs.length === 0 && (
                <p className='text-xs text-[#444] text-center py-4'>추가이미지가 없습니다.</p>
              )}
              {extraImgs.map((url, i) => (
                <div key={i} className='flex gap-2 items-center bg-[#0A0A0A] border border-[#1A1A1A] rounded p-2'>
                  <img
                    src={url} alt='' className='w-10 h-10 object-cover rounded shrink-0'
                    onError={e => { (e.target as HTMLImageElement).style.display = 'none' }}
                  />
                  <span className='flex-1 text-xs text-[#666] truncate'>{url}</span>
                  <div className='flex gap-1 shrink-0'>
                    <button onClick={() => moveExtra(i, -1)} className='text-[#666] text-xs px-1 hover:text-[#E5E5E5]'>▲</button>
                    <button onClick={() => moveExtra(i, 1)} className='text-[#666] text-xs px-1 hover:text-[#E5E5E5]'>▼</button>
                    <button onClick={() => removeExtra(i)} className='text-[#FF6B6B] text-xs px-1'>삭제</button>
                  </div>
                </div>
              ))}
            </div>
          )}

          {tab === 'detail' && (
            <div className='space-y-2'>
              <div className='flex gap-2 mb-3'>
                <input
                  className={INPUT}
                  value={urlInput}
                  onChange={e => setUrlInput(e.target.value)}
                  onKeyDown={e => { if (e.key === 'Enter') addDetail(urlInput) }}
                  placeholder='상세이미지 URL 입력'
                />
                <button onClick={() => addDetail(urlInput)} className='px-3 py-1.5 bg-[#FF8C00] text-white text-xs rounded hover:bg-[#E07B00]'>추가</button>
              </div>
              {details.length === 0 && (
                <p className='text-xs text-[#444] text-center py-4'>상세이미지가 없습니다.</p>
              )}
              {details.map((url, i) => (
                <div key={i} className='flex gap-2 items-center bg-[#0A0A0A] border border-[#1A1A1A] rounded p-2'>
                  <img
                    src={url} alt='' className='w-10 h-10 object-cover rounded shrink-0'
                    onError={e => { (e.target as HTMLImageElement).style.display = 'none' }}
                  />
                  <span className='flex-1 text-xs text-[#666] truncate'>{url}</span>
                  <div className='flex gap-1 shrink-0'>
                    <button onClick={() => moveDetail(i, -1)} className='text-[#666] text-xs px-1 hover:text-[#E5E5E5]'>▲</button>
                    <button onClick={() => moveDetail(i, 1)} className='text-[#666] text-xs px-1 hover:text-[#E5E5E5]'>▼</button>
                    <button onClick={() => removeDetail(i)} className='text-[#FF6B6B] text-xs px-1'>삭제</button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className='flex justify-end gap-2 px-4 py-3 border-t border-[#1A1A1A]'>
          <button onClick={onClose} className='px-4 py-1.5 text-sm text-[#999] hover:text-[#E5E5E5]'>취소</button>
          <button onClick={handleSave} className='px-4 py-1.5 bg-[#FF8C00] text-white text-sm rounded-lg font-medium hover:bg-[#E07B00]'>저장</button>
        </div>
      </div>
    </div>
  )
}
