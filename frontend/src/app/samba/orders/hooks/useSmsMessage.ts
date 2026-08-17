'use client'

import { useState, useRef, useCallback, useEffect } from 'react'
import {
  proxyApi,
  type SambaOrder,
  type SambaMarketAccount,
  type MessageLog,
} from '@/lib/samba/api/commerce'
import { forbiddenApi } from '@/lib/samba/legacy'
import { showAlert } from '@/components/samba/Modal'

interface SmsTemplate {
  id: string
  label: string
  msg: string
}

const DEFAULT_SMS_TEMPLATES: SmsTemplate[] = [
  { id: 't1', label: '주문취소안내', msg: '{{marketName}} 주문취소안내\n주문상품 : {{goodsName}}\n\n안녕하세요, {{rvcName}} 고객님.\n\n해당 상품이 일시적으로 시스템 오류로 노출되어 주문이 접수된 것으로 확인되었습니다.\n\n불편을 드려 정말 죄송합니다.\n\n빠른 환불 처리를 위해 "단순취소" 사유로 주문취소 해주시면 확인 후 바로 환불도와드리겠습니다.\n\n불편을 드려 진심으로 죄송하며, 더 나은 서비스로 보답드리겠습니다. 감사합니다.' },
  { id: 't2', label: '가격변동 취소', msg: '{{marketName}} 가격변동 안내\n주문상품 : {{goodsName}}\n\n안녕하세요 {{rvcName}} 고객님\n\n해당 제품 공급처에서 가격을 변동하여 안내드립니다.\n취소 후 재주문 부탁드립니다.' },
  { id: 't3', label: '국내상품 발주안내', msg: '{{marketName}} 주문상품 발주 완료\n주문상품 : {{goodsName}}\n\n안녕하세요 {{rvcName}} 고객님^^ 발주 완료되었습니다. 배송완료까지 영업일기준 2~3일정도 소요됩니다.' },
  { id: 't4', label: '반품비', msg: '{{marketName}} 반품비 안내\n상품명 : {{goodsName}}\n\n반품비 안내드립니다.\n교환비용 8,000원 발생(고객변심)하므로 따로 개별 문자 안내드리겠습니다.' },
  { id: 't5', label: '반품안내문자', msg: '{{marketName}} 반품 안내\n주문상품 : {{goodsName}}\n\n안녕하세요 {{rvcName}} 고객님\n반품신청으로 문자안내드립니다.\n교환 접수시 회수기사님 방문2-3일내 이루어지며 회수된 상품 해당부서로 이동하여 검수진행과정 진행됩니다.' },
  { id: 't6', label: '발주 후 품절', msg: '{{marketName}} 품절안내\n주문상품 : {{goodsName}}\n\n안녕하세요 {{rvcName}} 고객님. 저희가 해당 제품 발주를 넣었는데 공급처에서 품절이라고 연락이 왔습니다.\n취소 처리 도와드리겠습니다.' },
  // 더 망고 카카오 발송양식 이식 — 주문 라이프사이클 안내 (변수는 삼바 기존 태그로 매핑)
  { id: 'dm_order_complete', label: '주문완료 안내', msg: '[{{rvcName}}님] 주문완료 안내\n□ 주문마켓 : {{marketName}}\n□ 주문번호 : {{OrderName}}\n\n배송준비가 시작되었습니다.\n\n배송지연(불가) 시 고객님께 추가 안내 해 드릴 예정이며, 따로 연락을 드리지 않을 경우 "영업일 기준 1~2 일 내" 정상 출고 됩니다.\n\n빠르고 안전하게 주문하신 상품 전달해드리겠습니다. 좋은 하루 되세요.' },
  { id: 'dm_shipping_prep', label: '배송준비중(출고진행중)', msg: '안녕하세요 {{rvcName}}님\n[{{marketName}}]에서 주문해주신 "{{goodsName}}" 상품이 준비되어 배송준비중(출고진행중)에 있습니다.\n\n출고진행중 단계에서는 제품이 패킹되어 택배사로 인계 진행 단계이기에 주문취소 시 왕복 환불배송료 부과될 수 있는 점 양해부탁드립니다.\n\n빠르고 안전하게 받아보실 수 있도록 준비하겠습니다. 감사합니다.' },
  { id: 'dm_ship_ready', label: '주문/배송 준비완료', msg: '[{{rvcName}}님] 주문/배송 준비완료 안내\n□ 주문마켓 : {{marketName}}\n□ 주문번호 : {{OrderName}}\n\n안녕하세요 {{rvcName}}님\n[{{marketName}}]에서 주문해주신 "{{goodsName}}" 상품이 준비되어 배송사로 인계되었습니다.\n\n제품이 패킹되어 택배사로 인계 진행 단계이기에 주문취소 시 왕복 환불배송료 부과될 수 있는 점 양해부탁드립니다.\n\n배송지연(불가) 시 고객님께 추가 안내 해 드릴 예정이며, 따로 연락을 드리지 않을 경우 "영업일 기준 1~2 일 내" 정상 출고 됩니다.\n\n빠르고 안전하게 받아보실 수 있도록 준비하겠습니다. 감사합니다.' },
  { id: 'dm_return_received', label: '반품/교환 접수', msg: '□ 주문번호 : {{OrderName}}\n\n안녕하세요 {{rvcName}}님\n[{{marketName}}]에서 주문해주신 "{{goodsName}}" 상품 반품(또는 교환)을 접수했습니다.\n\n"내일 방문수거 예정"이며 반품하실 제품의 모든 구성품을 갖춰 수거될 수 있도록 준비(문 밖 배치)해 놓아 주시기 바랍니다.\n※ 미수거시 다음날 (또는 택배 시작 재개일) 수거 예정\n\n수거가 이루어지지 않는다면 반품이 철회되오니 꼭 회신 부탁드립니다.\n\n반품수거 이후 택배기사님이 남겨주시는 반품송장을 꼭 소지하시기 바랍니다.' },
  { id: 'dm_cancel_stock', label: '취소안내(입고미정)', msg: '안녕하세요 {{rvcName}}님\n[{{marketName}}]에서 주문해주신 "{{goodsName}}" 상품은 브랜드사 사정에 따라 입고일자가 확정되지 않고 있습니다.\n\n따라서 주문하신 상품을 빠르게 취소 처리 도와드리려 합니다.\n\n가장 빠르게 환불 받으실 수 있는 "필요없음/단순변심" 으로 접수해주시면 바로 승인처리 도와드리겠습니다.\n※ 해당 건 자동 승인처리\n\n불편을 드려 대단히 죄송합니다.' },
  // [2026-07-30] 사용자 상시 발송 양식 이식 — 원문 그대로, {수령인}/{마켓명}/{상품명}만 삼바 태그로 매핑
  { id: 'wjm0_order_success', label: '0.주문성사 안내', msg: '안녕하세요 {{rvcName}}님\n[{{marketName}}]에서 주문해주신 "{{goodsName}}" 상품이 준비되어 배송준비중(출고진행중)에 있습니다.\n\n출고진행중 단계에서는 제품이 패킹되어 택배사로 인계 진행 단계이기에 주문취소 시 왕복 환불배송료 부과될 수 있는 점 양해부탁드립니다.\n\n빠르고 안전하게 받아보실 수 있도록 준비하겠습니다. 감사합니다.' },
  { id: 'wjm1_1_cancel_induce', label: '1-1.주문취소 유도', msg: '[{{marketName}}] 주문 관련 안내드립니다.\n\n주문상품 : {{goodsName}}\n\n안녕하세요, {{rvcName}} 고객님.\n\n해당 상품이 일시적으로 시스템 오류로 노출되어 주문이 접수된 것으로 확인되었습니다.\n불편을 드려 정말 죄송합니다.\n\n빠른 환불 처리를 위해 ✅ 출고중지(취소 요청) 해주시면\n확인 후 바로 환불을 도와드리겠습니다.\n\n불편을 드려 진심으로 죄송하며, 더 나은 서비스로 보답드리겠습니다. 감사합니다.\n\n※ 필요없음(단순변심) 사유 선택시 자동취소 처리' },
  { id: 'wjm1_2_price_soldout', label: '1-2.가격/품절 안내', msg: '[{{marketName}} 구매상품 안내]\n안녕하세요 {{rvcName}}님 [{{marketName}}]에서 주문해주신 "{{goodsName}}" 상품이 현재 재고정보 오류(재입고 불투명)/가격정보 오류로 부득이하게 주문취소 처리 될 예정입니다. \n\n불편드린 점 대단히 다시 한 번 사과의 말씀 올립니다.\n\n빠른 환불을 의해 본사에서 직접 주문취소 처리 진행해드릴 예정이며, 환불이 이뤄지지 않았을 경우,  주문 취소 요청해주시면 빠르게 취소 처리 승인 도와드리겠습니다. \n\n더 좋은 제품으로 만나뵙겠습니다.\n감사합니다.' },
  { id: 'wjm1_3_long_uncancelled', label: '1-3.장기 미취소 회신', msg: '안녕하세요 {{rvcName}}님\n{{marketName}}에서 주문해주신 {{goodsName}} 상품에 대한 주문취소가 이뤄지지 않아 아직 환불이 되고 있지 않습니다. 쿠팡에서 주문취소 버튼을 눌러 빠르게 정상 환불 받아주시기 바랍니다. ' },
  { id: 'wjm2_0_2_proof_request', label: '2-0-2.반품 증빙요청', msg: '안녕하세요 {{rvcName}}님\n[{{marketName}}]에서 반품신청하신 "{{goodsName}}" 상품에 클레임 사유 관련 증빙(사진)이 접수되지 않았습니다. 교환(반품)사유로 적어주신 관련 사진 회신부탁드립니다.\n\n별다른 회신이 없으실 경우  반드시 "단순변심" 으로 체킹되어야 정상 반품처리 되오니 반드시 회신 부탁드립니다,' },
  { id: 'wjm2_0_reason_fix', label: '2-0.반품사유 수정요청', msg: '안녕하세요 {{rvcName}}님\n[{{marketName}}]에서 주문해주신 "{{goodsName}}" 상품 반품접수 및 제품 수거를 위하여 배차 진행 예정입니다.\n\n"오배송"이 아닌 경우 반드시 "단순변심" 으로 체킹되어야 반품승인이 이뤄져 정상적으로 환불이 이뤄집니다. 사이즈 오류 등은 단순변심에 해당합니다. \n\n수정이 번거로우신 경우 아래의 계좌로 반품비 입금 후 회신 주셔도 무방합니다.  그럼 진행 후 회신부탁드립니다.\n\n[계좌안내]\n신한/ 684-02-058490\n입금주: 우준명\n반품비: 8,000원\n\n※ 해당 내용 이행 후 확인 문자 회신 주시면 보다 빠른 처리가 가능합니다.' },
  { id: 'wjm2_1_return_received', label: '2-1.반품 접수(제품준비)', msg: '안녕하세요 {{rvcName}}님\n\n[{{marketName}}]에서 주문해주신 "{{goodsName}}" 상품 반품(또는 교환) 요청 확인하였습니다.\n\n제품 수거를 위하여 택배사를 {{rvcName}}님께 배차 접수했습니다.\n\n"내일을 포함한 3일 내 방문수거" 예정입니다. 따라서 "내일 오전"부터 반품하실 제품의 모든 구성품을 갖춰 수거할 수 있도록 준비(문 밖 배치)에 하여 주시기 바랍니다.\n\n만약 당일 이뤄지지 않는다면 송장 취소가 진행될 수 있으니 꼭 수거될 수 있도록 준비 부탁드립니다. 더불어 제품이 분실되지 않도록 유의 부탁드립니다.\n※ 제품의 택이 제거되거나 사용감이 있는 경우, 받으신 그대로 이중박스(패키지) 포장이 아닌 경우 제품은 반송됩니다.' },
  { id: 'wjm2_2_reason_fee', label: '2-2.반품사유/반품비', msg: '안녕하세요. 고객님,\n반품사유 수정 또는 반품비 확인이 되지 않을 경우 반품 접수가 정상적으로 이뤄지지 않습니다.\n\n별다른 회신이 없을 시 반품 철회될 수 있으니 꼭 회신 부탁드립니다.' },
  { id: 'wjm2_3_exchange_fee', label: '2-3.교환비용 청구', msg: '안녕하세요 {{rvcName}}님\n[{{marketName}}]에서 주문해주신 "{{goodsName}}" 상품 교환 진행에정입니다.\n\n교환 배송비 입금 후 접수 진행 도와드리겠습니다. 아래의 계좌로 입금 후 입금자 성함과 함께 회신 부탁드립니다.\n\n장시간 입금이 되지 않을 경우 교환 없이 자동으로 구매 확정이 될 수 있으니 가급적 빠른시간 내 입금 부탁드립니다.\n\n[계좌번호]\n-계좌:684-02-058490/ 신한/ 우준명\n-(교환)반품비: 8.000원' },
  { id: 'wjm2_4_pickup_confirm', label: '2-4.수거 확인요청', msg: '안녕하세요 {{rvcName}}님\n[{{marketName}}]에서 반품요청주신 "{{goodsName}}" 상품이 아직 수거되지 않은 것으르 확인됩니다.\n\n혹시 수거가 완료되었다면 기사님이 남겨주신 송장 사진 촬영 후 회신 부탁드립니다.\n\n미수거 되었다면 회신부탁드립니다.  내일 다시 수거택배 접수 해드리겠습니다.\n\n회신이 없을 경우 반품 철회에 동의 해주신 것으라 간주되어 반품철회 요청 진행됩니다.\n\n감사합니다.' },
  { id: 'wjm2_5_return_withdraw', label: '2-5.반품철회', msg: '안녕하세요 {{rvcName}}님\n[{{marketName}}]에서 주문해주신 "{{goodsName}}" 상품 반품(또는 교환) 수거를 위해 기사님이 방문하셨으나, 미수거 된 것으로 확인됩니다.\n\n혹시 수거가 되었다면 회신 부탁드립니다. \n\n내일 다시 재배차 예정이며  제품 미수거, 별다른 회신이 없으실 경우 해당 반품 건은 철회진행해드리겠습니다.' },
  { id: 'wjm9_1_soldout_cream', label: '9-1.솔드아웃/크림 주문', msg: '[배송기한 / 교환 반품 불가 안내-답장필수]\n\n{{rvcName}}님 안녕하세요. 저희 코코블랭크를 이용해주셔셔 감사드립니다. 주문해주신 상품은 다행히 재고가 있어 구매 가능하신 상품입니다\n\n{{marketName}}에서 주문해주신 {{goodsName}} 상품은 주문 후 검수센터로 이동하여 철저한 정가품 검수 후 발송예정입니다. \n문제없는 상품을 보내드리기 위한 과정이며, 상품 출고까지 영업일 기준  약 7일이 소요됩니다. \n\n또한 한정판 (모든 마켓 품절) 제품으로 어렵게 구해 보내드리는 제품인 만큼 구매 이후 취소/교환/환불이  절대 불가하니 꼭 확인 및 주문처리에 대한 고객님 "동의" 답장 부탁드립니다.\n\n동일 내용은 제품 상세페이지에도 기재되어 있으니 참고부탁드립니다.\n\n그럼 주문 이행 여부 관련 동의/비동의 회신 부탁드립니다.' },
  { id: 'wjm9_2_soldout_cream_after', label: '9-2.솔드아웃 성사이후', msg: '안녕하세요 {{rvcName}}님 {{marketName}}에서 주문해주신 {{goodsName}} 상품이 검수센터로 배송중입니다. 검수 기간은 영업일 기준 4~7일이 소요되며, 검수가 끝나고 이상없는 제품일 경우 즉시 출고 진행하겠습니다\n감사합니다.' },
  { id: 'wjm10_china_noreturn', label: '10.중국구매대행 반품불가', msg: '[교환 반품 불가 안내-답장필수]\n\n{{rvcName}}님 안녕하세요. 저희몰을 믿고 이용해주감사드립니다. 주문해주신 주문제작상품으로  고객님 오더 회신 이후에 제작 후 발송처리 됩니다. \n\n제작기간은 약 7~10일 정도 소요 됩니다.\n\n또한 해당상품의 경우 주문제작, 해외 배송 제품인 국내로 배송 진행 이후에는 교환, 반품이 불가합니다\n\n따라서 해당 건에 대한 동의 회신 주시면 주문이행 도와드리도록 하겠습니다.\n\n주문처리에 대한 고객님 "동의" 답장 부탁드립니다. 해당 문자에 동의 회신 해주시면 됩니다.\n\n그럼 주문 이행 여부 관련 동의/비동의 회신 부탁드립니다.\n\n감사합니다.' },
]

export function useSmsMessage(accounts: SambaMarketAccount[]) {
  const [msgModal, setMsgModal] = useState<{ type: 'sms' | 'kakao'; order: SambaOrder } | null>(null)
  const [msgText, setMsgText] = useState('')
  const [msgPhone, setMsgPhone] = useState('')
  const [msgSending, setMsgSending] = useState(false)
  const msgTextRef = useRef<HTMLTextAreaElement>(null)
  const [msgHistory, setMsgHistory] = useState<MessageLog[]>([])
  const [sentFlags, setSentFlags] = useState<Record<string, { sms: boolean; kakao: boolean }>>({})

  // SMS 템플릿 — 서버(forbidden settings) 영속화, localStorage는 첫 페인트 캐시만
  const [smsTemplates, setSmsTemplates] = useState<SmsTemplate[]>(() => {
    try {
      const saved = typeof window !== 'undefined' ? localStorage.getItem('samba_sms_templates') : null
      return saved ? JSON.parse(saved) : DEFAULT_SMS_TEMPLATES
    } catch { return DEFAULT_SMS_TEMPLATES }
  })
  // 서버 로드 완료 전 저장을 막는 가드 — 기본값이 서버 데이터를 덮어쓰는 race 방지
  const templateLoadedRef = useRef(false)
  const [templateEditModal, setTemplateEditModal] = useState<SmsTemplate | null>(null)
  const [isNewTemplate, setIsNewTemplate] = useState(false)

  useEffect(() => {
    forbiddenApi.getSetting('sms_templates').then((val) => {
      if (Array.isArray(val) && val.length > 0) {
        setSmsTemplates(val as SmsTemplate[])
        localStorage.setItem('samba_sms_templates', JSON.stringify(val))
      } else {
        // 서버에 없으면 로컬 값을 1회 승격 저장
        const local = (() => {
          try {
            const s = typeof window !== 'undefined' ? localStorage.getItem('samba_sms_templates') : null
            return s ? (JSON.parse(s) as SmsTemplate[]) : null
          } catch { return null }
        })()
        const toSave = (local && local.length > 0) ? local : DEFAULT_SMS_TEMPLATES
        forbiddenApi.saveSetting('sms_templates', toSave).catch(() => {})
        setSmsTemplates(toSave)
      }
    }).catch(() => {}).finally(() => {
      templateLoadedRef.current = true
    })
  }, [])

  const saveSmsTemplates = (templates: SmsTemplate[]) => {
    if (!templateLoadedRef.current) return
    setSmsTemplates(templates)
    localStorage.setItem('samba_sms_templates', JSON.stringify(templates))
    forbiddenApi.saveSetting('sms_templates', templates).catch(() => {})
  }
  const openNewTemplate = () => {
    setIsNewTemplate(true)
    setTemplateEditModal({ id: `t_${Date.now()}`, label: '', msg: '' })
  }
  const openEditTemplate = (t: SmsTemplate) => {
    setIsNewTemplate(false)
    setTemplateEditModal({ ...t })
  }
  const saveTemplate = () => {
    if (!templateEditModal) return
    if (isNewTemplate) {
      saveSmsTemplates([...smsTemplates, templateEditModal])
    } else {
      saveSmsTemplates(smsTemplates.map(t => t.id === templateEditModal.id ? templateEditModal : t))
    }
    setTemplateEditModal(null)
  }
  const deleteTemplate = (id: string) => {
    saveSmsTemplates(smsTemplates.filter(t => t.id !== id))
  }
  // 기본 제공 템플릿 중 현재 목록에 없는 것(id 기준)만 비파괴적으로 추가.
  // 서버에 이미 템플릿이 저장된 사용자는 DEFAULT 변경분이 자동 노출되지 않으므로 수동 병합용.
  const addDefaultTemplates = () => {
    if (!templateLoadedRef.current) return
    const existingIds = new Set(smsTemplates.map(t => t.id))
    const missing = DEFAULT_SMS_TEMPLATES.filter(t => !existingIds.has(t.id))
    if (missing.length === 0) {
      showAlert('추가할 기본 템플릿이 없습니다 (이미 모두 있음)', 'info')
      return
    }
    saveSmsTemplates([...smsTemplates, ...missing])
    showAlert(`기본 템플릿 ${missing.length}개를 추가했습니다`, 'success')
  }

  const insertMsgTag = (tag: string) => {
    const el = msgTextRef.current
    if (!el) { setMsgText(prev => prev + tag); return }
    const start = el.selectionStart
    const end = el.selectionEnd
    const newVal = msgText.slice(0, start) + tag + msgText.slice(end)
    setMsgText(newVal)
    requestAnimationFrame(() => { el.selectionStart = el.selectionEnd = start + tag.length; el.focus() })
  }

  const renderMsgTemplate = useCallback((template: string, order: SambaOrder) => {
    const matchedAccount = accounts.find(account => {
      if (order.channel_name && account.market_name && order.channel_name.includes(account.market_name)) return true
      if (order.channel_name && account.account_label && order.channel_name.includes(account.account_label)) return true
      return false
    })
    const sellerName = matchedAccount?.business_name || matchedAccount?.seller_id || matchedAccount?.account_label || ''
    let marketName = matchedAccount?.market_name || order.channel_name || ''
    // 플레이오토 주문은 실제 판매처가 sales_channel_alias(예: GSSHOP(고경))에 있음 → 판매처명만 추출(괄호 안 계정명 제외)
    if (marketName.includes('플레이오토')) {
      const alias = String(order.sales_channel_alias || '').trim()
      if (alias) marketName = alias.split('(')[0].trim() || alias
    }
    const variables: Record<string, string> = {
      sellerName,
      marketName,
      OrderName: order.order_number || '',
      rvcName: order.customer_name || '',
      rcvHPNo: order.customer_phone || '',
      goodsName: order.product_name || '',
    }

    return template
      .replace(/\{\{(sellerName|marketName|OrderName|rvcName|rcvHPNo|goodsName)\}\}/g, (_, key: keyof typeof variables) => variables[key] || '')
      .replace(/\{\{[^{}]+\}\}/g, '')
  }, [accounts])

  const openMsgModal = (type: 'sms' | 'kakao', order: SambaOrder) => {
    setMsgModal({ type, order })
    setMsgText('')
    setMsgPhone(order.customer_phone || '')
    setMsgHistory([])
    proxyApi.fetchMessageHistory(order.id).then(setMsgHistory).catch(() => {})
  }

  const handleSendMsg = async () => {
    if (!msgModal || !msgText.trim()) {
      showAlert('메시지를 입력해주세요', 'error')
      return
    }
    const phone = msgPhone.replace(/[^0-9]/g, '')
    if (!phone) {
      showAlert('전화번호를 입력해주세요', 'error')
      return
    }
    setMsgSending(true)
    try {
      const renderedMsg = renderMsgTemplate(msgText, msgModal.order).trim()
      if (!renderedMsg) {
        showAlert('치환 후 발송할 메시지가 비어 있습니다.', 'error')
        return
      }
      const orderId = msgModal.order.id
      const msgType = msgModal.type
      let res: { success: boolean; message: string }
      if (msgType === 'sms') {
        res = await proxyApi.sendSms(phone, renderedMsg, '', orderId, msgText)
      } else {
        res = await proxyApi.sendKakao(phone, renderedMsg, '', '', orderId, msgText)
      }
      if (res.success) {
        showAlert(res.message, 'success')
        setSentFlags(prev => ({
          ...prev,
          [orderId]: { ...prev[orderId], sms: msgType === 'sms' ? true : (prev[orderId]?.sms ?? false), kakao: msgType === 'kakao' ? true : (prev[orderId]?.kakao ?? false) },
        }))
        setMsgModal(null)
        setMsgText('')
      } else {
        showAlert(res.message, 'error')
      }
    } catch (e) {
      showAlert(e instanceof Error ? e.message : '발송 실패', 'error')
    } finally {
      setMsgSending(false)
    }
  }

  return {
    msgModal, setMsgModal,
    msgText, setMsgText,
    msgPhone, setMsgPhone,
    msgSending,
    msgTextRef,
    msgHistory,
    sentFlags, setSentFlags,
    smsTemplates,
    templateEditModal, setTemplateEditModal,
    isNewTemplate,
    openNewTemplate,
    openEditTemplate,
    saveTemplate,
    deleteTemplate,
    addDefaultTemplates,
    insertMsgTag,
    openMsgModal,
    handleSendMsg,
  }
}
