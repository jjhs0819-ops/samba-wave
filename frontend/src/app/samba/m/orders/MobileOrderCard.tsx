'use client'

import { useState } from 'react'
import type { SambaOrder, SambaSourcingAccount } from '@/lib/samba/legacy'
import { orderApi } from '@/lib/samba/api/commerce'
import { showAlert } from '@/components/samba/Modal'
import type { Palette } from '@/lib/samba/colors'
import { makeInputStyle, fmtNum } from '@/lib/samba/styles'
import { STATUS_MAP } from '../../orders/constants'
import { splitCustomerAddress } from '../../orders/utils/copyHelpers'
import { parseActionTags, serializeActionTags } from '../../orders/utils/actionTag'
import {
  buildHumanText,
  buildPayloadText,
  cleanName,
  writeClipboard,
  type AutofillPayload,
} from './payload'

/** 데스크톱 주문탭과 동일한 사칙연산 허용 입력 (예: `30000*.973+2300`) */
function evalExpr(raw: string): number | null {
  const expr = raw.replace(/,/g, '').trim()
  if (!expr) return 0
  if (!/^[\d+\-*/.() ]+$/.test(expr)) return null
  try {
    const result = Function(`"use strict";return (${expr})`)()
    if (typeof result !== 'number' || !Number.isFinite(result) || result < 0) return null
    return Math.round(result)
  } catch {
    return null
  }
}

/** 데스크톱과 동일 — 소싱주문번호 입력 시 진행된 상태는 역행시키지 않는다. */
const ADVANCED_STATUSES = [
  'shipping', 'delivered', 'confirmed', 'cancelled', 'returned',
  'cancel_requested', 'return_requested', 'ship_failed',
]

/** 상태 드롭다운에서 감추는 값 — 데스크톱 OrdersTable 과 동일 */
const HIDDEN_STATUSES = ['preparing', 'cancel_reject_pending', 'return_completed', 'undeliverable']

interface Props {
  order: SambaOrder
  c: Palette
  sourcingAccounts: SambaSourcingAccount[]
  /** 사무실 전화 — 수령인 연락처로 고정 사용 */
  officePhone: string
  onPatch: (id: string, patch: Partial<SambaOrder>) => void
}

export default function MobileOrderCard({ order: o, c, sourcingAccounts, officePhone, onPatch }: Props) {
  const [orderNumber, setOrderNumber] = useState<string | null>(null)
  const [cost, setCost] = useState<string | null>(null)
  const [memo, setMemo] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  const addr = splitCustomerAddress(o.customer_address, o.customer_address_detail)
  const activeTags = parseActionTags(o.action_tag ?? null)

  const payload: AutofillPayload = {
    orderId: o.id,
    name: cleanName(o.customer_name),
    // 연락처는 항상 사무실 전화 — 데스크톱 triggerPlaceOrder 와 동일 규칙
    phone: officePhone,
    zip: o.customer_postal_code || '',
    addr: addr.base,
    detail: addr.detail,
    option: o.product_option || '',
    qty: o.quantity,
  }

  const patch = async (data: Partial<SambaOrder>) => {
    setSaving(true)
    try {
      await orderApi.update(o.id, data)
      onPatch(o.id, data)
    } catch (e) {
      showAlert(e instanceof Error ? e.message : '저장 실패', 'error')
    } finally {
      setSaving(false)
    }
  }

  const saveOrderNumber = async () => {
    if (orderNumber === null) return
    const val = orderNumber.trim()
    setOrderNumber(null)
    if (val === (o.sourcing_order_number ?? '')) return
    setSaving(true)
    try {
      await orderApi.update(o.id, { sourcing_order_number: val })
      const next: Partial<SambaOrder> = { sourcing_order_number: val }
      // 소싱주문번호 입력 → '배송대기중' 자동 전환 (status 는 전용 엔드포인트로만 반영됨)
      if (val && !ADVANCED_STATUSES.includes(o.status)) {
        await orderApi.updateStatus(o.id, 'wait_ship')
        next.status = 'wait_ship'
      }
      onPatch(o.id, next)
    } catch {
      showAlert('소싱주문번호 저장 실패', 'error')
    } finally {
      setSaving(false)
    }
  }

  const saveCost = async () => {
    if (cost === null) return
    const parsed = evalExpr(cost)
    setCost(null)
    if (parsed === null || parsed === o.cost) return
    await patch({ cost: parsed })
  }

  const saveMemo = async () => {
    if (memo === null) return
    const val = memo.trim()
    setMemo(null)
    if (val === (o.notes ?? '')) return
    await patch({ notes: val })
  }

  const toggleTag = async (key: string) => {
    const next = activeTags.includes(key)
      ? activeTags.filter((t) => t !== key)
      : [...activeTags, key]
    await patch({ action_tag: serializeActionTags(next) })
  }

  /**
   * 소싱처 열기 — 자동입력 페이로드를 클립보드에 넣고 새 탭으로 이동.
   * iOS 사파리는 await 뒤의 window.open 을 팝업으로 보고 차단하므로 앵커 기본동작에 맡기고,
   * 클립보드 쓰기는 제스처 안에서 시작만 시킨다(await 하지 않음).
   */
  const onOpenSource = (e: React.MouseEvent<HTMLAnchorElement>) => {
    if (!o.source_url) {
      e.preventDefault()
      showAlert('원주문 링크(source_url)가 없습니다', 'error')
      return
    }
    if (!officePhone) {
      e.preventDefault()
      showAlert('설정 > 사무실 배송정보에 전화번호를 먼저 입력해주세요', 'error')
      return
    }
    void writeClipboard(buildPayloadText(payload))
  }

  const copyHuman = async () => {
    const ok = await writeClipboard(buildHumanText(payload))
    showAlert(ok ? '배송정보를 복사했습니다' : '복사 실패', ok ? 'info' : 'error')
  }

  const inp = { ...makeInputStyle(c), fontSize: '1rem', padding: '0.5rem 0.625rem', width: '100%' }
  const statusMeta = STATUS_MAP[o.status]

  return (
    <div
      style={{
        background: c.surface,
        border: `1px solid ${c.border}`,
        borderRadius: '10px',
        padding: '0.75rem',
        marginBottom: '0.75rem',
        opacity: saving ? 0.6 : 1,
      }}
    >
      {/* 상품 */}
      <div style={{ display: 'flex', gap: '0.625rem' }}>
        {o.product_image && (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={o.product_image}
            alt=""
            style={{ width: 64, height: 64, objectFit: 'cover', borderRadius: '6px', flexShrink: 0 }}
          />
        )}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', gap: '0.375rem', flexWrap: 'wrap', marginBottom: '0.25rem' }}>
            {o.source_site && (
              <span style={{ fontSize: '0.6875rem', padding: '0.0625rem 0.375rem', borderRadius: '4px', background: c.chipNeutralBg, color: c.chipNeutralText }}>
                {o.source_site}
              </span>
            )}
            {statusMeta && (
              <span style={{ fontSize: '0.6875rem', padding: '0.0625rem 0.375rem', borderRadius: '4px', background: statusMeta.bg, color: statusMeta.text, fontWeight: 700 }}>
                {statusMeta.label}
              </span>
            )}
            {o.quantity > 1 && (
              <span style={{ fontSize: '0.6875rem', padding: '0.0625rem 0.375rem', borderRadius: '4px', background: c.warn, color: '#fff', fontWeight: 700 }}>
                수량 {o.quantity}
              </span>
            )}
          </div>
          <div style={{ fontSize: '0.875rem', color: c.text, fontWeight: 600, lineHeight: 1.3 }}>
            {o.product_name || '-'}
          </div>
          <div style={{ fontSize: '0.8125rem', color: c.textSub, marginTop: '0.125rem' }}>
            {o.product_option || '옵션 없음'}
          </div>
          <div style={{ fontSize: '0.75rem', color: c.textMuted, marginTop: '0.125rem' }}>
            {o.channel_name || ''} {o.order_number}
          </div>
        </div>
      </div>

      {/* 고객 배송정보 */}
      <div style={{ marginTop: '0.625rem', padding: '0.5rem', background: c.surfaceAlt, borderRadius: '6px', fontSize: '0.8125rem', color: c.text, lineHeight: 1.5 }}>
        <div style={{ fontWeight: 700 }}>{cleanName(o.customer_name) || '-'}</div>
        <div>{o.customer_postal_code ? `[${o.customer_postal_code}] ` : ''}{addr.base || '-'}</div>
        {addr.detail && <div>{addr.detail}</div>}
        <div style={{ color: c.textMuted, fontSize: '0.75rem', marginTop: '0.125rem' }}>
          수령인 연락처는 사무실 전화({officePhone || '미설정'})로 입력됩니다
        </div>
      </div>

      {/* 액션 */}
      <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.625rem' }}>
        <a
          href={o.source_url || '#'}
          target="_blank"
          rel="noopener noreferrer"
          onClick={onOpenSource}
          style={{ flex: 2, padding: '0.625rem', borderRadius: '8px', background: c.btnSolidBg, color: c.btnSolidText, fontSize: '0.9375rem', fontWeight: 700, textAlign: 'center', textDecoration: 'none' }}
        >
          소싱처 열기
        </a>
        <button
          onClick={copyHuman}
          style={{ flex: 1, padding: '0.625rem', borderRadius: '8px', border: `1px solid ${c.btnBorder}`, background: c.btnBg, color: c.btnText, fontSize: '0.9375rem', fontWeight: 600 }}
        >
          정보복사
        </button>
      </div>

      {/* 완료 입력 */}
      <div style={{ marginTop: '0.625rem', display: 'flex', flexDirection: 'column', gap: '0.375rem' }}>
        <select
          value={o.sourcing_account_id || ''}
          onChange={(e) => patch({ sourcing_account_id: (e.target.value || null) as unknown as string })}
          style={{ ...inp, fontWeight: 600 }}
        >
          <option value="">주문계정 선택</option>
          {sourcingAccounts.map((sa) => (
            <option key={sa.id} value={sa.id}>
              {sa.site_name} · {sa.account_label ? `${sa.account_label}(${sa.username})` : sa.username}
            </option>
          ))}
          <option value="etc">기타</option>
        </select>

        <input
          type="text"
          inputMode="numeric"
          placeholder={o.sourcing_account_id ? '소싱주문번호' : '주문계정 먼저 선택'}
          disabled={!o.sourcing_account_id}
          value={orderNumber ?? o.sourcing_order_number ?? ''}
          onChange={(e) => setOrderNumber(e.target.value)}
          onBlur={saveOrderNumber}
          style={{ ...inp, opacity: o.sourcing_account_id ? 1 : 0.5 }}
        />

        <input
          type="text"
          inputMode="text"
          placeholder="실구매가 (식 가능: 30000*.973+2300)"
          value={cost ?? (o.cost ? fmtNum(o.cost) : '')}
          onChange={(e) => setCost(e.target.value.replace(/[^\d+\-*/.() ]/g, ''))}
          onBlur={saveCost}
          style={{ ...inp, textAlign: 'right' }}
        />

        <select
          value={o.status}
          onChange={async (e) => {
            const next = e.target.value
            setSaving(true)
            try {
              await orderApi.updateStatus(o.id, next)
              onPatch(o.id, { status: next })
            } catch {
              showAlert('상태 변경 실패', 'error')
            } finally {
              setSaving(false)
            }
          }}
          style={{ ...inp, fontWeight: 600 }}
        >
          {Object.entries(STATUS_MAP)
            .filter(([k]) => !HIDDEN_STATUSES.includes(k))
            .map(([k, v]) => (
              <option key={k} value={k}>{v.label}</option>
            ))}
        </select>

        <input
          type="text"
          placeholder="메모"
          value={memo ?? o.notes ?? ''}
          onChange={(e) => setMemo(e.target.value)}
          onBlur={saveMemo}
          style={inp}
        />

        {/* 직원 태그 */}
        <div style={{ display: 'flex', gap: '0.5rem' }}>
          {[
            { key: 'staff_a', label: '직원A', color: '#7C3AED' },
            { key: 'staff_b', label: '직원B', color: '#DB2777' },
          ].map((t) => {
            const on = activeTags.includes(t.key)
            return (
              <button
                key={t.key}
                onClick={() => toggleTag(t.key)}
                style={{
                  flex: 1,
                  padding: '0.5rem',
                  borderRadius: '8px',
                  border: `1px solid ${on ? t.color : c.chipNeutralBorder}`,
                  background: on ? t.color : c.chipNeutralBg,
                  color: on ? '#fff' : c.chipNeutralText,
                  fontSize: '0.875rem',
                  fontWeight: 600,
                }}
              >
                {t.label}
              </button>
            )
          })}
        </div>
      </div>
    </div>
  )
}
