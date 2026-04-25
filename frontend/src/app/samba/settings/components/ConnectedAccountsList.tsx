'use client'

import { Dispatch, SetStateAction } from 'react'
import type { SambaMarketAccount } from '@/lib/samba/api/commerce'

type OutboundPlace = { code: string; name: string; address: string }
type InboundPlace = { code: string; name: string; address: string; address_detail: string; zipcode: string; phone: string }

interface Props {
  marketKey: string
  accounts: SambaMarketAccount[]
  editingAccountId: string | null
  setEditingAccountId: (v: string | null) => void
  setStoreData: Dispatch<SetStateAction<Record<string, Record<string, string>>>>
  setCoupangOutboundList: Dispatch<SetStateAction<OutboundPlace[]>>
  setCoupangInboundList: Dispatch<SetStateAction<InboundPlace[]>>
  handleAccountDelete: (id: string) => void | Promise<void>
}

export function ConnectedAccountsList(props: Props) {
  const {
    marketKey, accounts, editingAccountId, setEditingAccountId, setStoreData,
    setCoupangOutboundList, setCoupangInboundList, handleAccountDelete,
  } = props
  const marketAccounts = accounts.filter(a => a.market_type === marketKey)

  return (
    <div style={{ width: '260px', flexShrink: 0 }}>
      <div style={{ fontSize: '0.82rem', fontWeight: 600, color: '#888', marginBottom: '0.5rem' }}>연결 계정</div>
      {marketAccounts.length === 0 ? (
        <div style={{ fontSize: '0.78rem', color: '#555', padding: '0.5rem 0' }}>등록된 계정 없음</div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.375rem' }}>
          {marketAccounts.map(a => (
            <div key={a.id} style={{
              display: 'flex', alignItems: 'center', gap: '0.5rem',
              padding: '0.4rem 0.625rem', background: 'rgba(255,255,255,0.02)',
              borderRadius: '6px', border: '1px solid rgba(45,45,45,0.5)',
            }}>
              <div style={{ flex: 1, minWidth: 0, fontSize: '0.8rem', color: '#E5E5E5', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {a.account_label}
              </div>
              <button
                onClick={() => {
                  setEditingAccountId(a.id)
                  const accData = (a.additional_fields || {}) as Record<string, string>
                  const formData: Record<string, string> = {
                    businessName: a.business_name || '',
                    storeId: a.seller_id || '',
                    ...accData,
                  }
                  setStoreData(prev => ({ ...prev, [marketKey]: formData }))
                  if (marketKey === 'coupang') {
                    const outCode = formData.outboundShippingPlaceCode || ''
                    const outName = formData.outboundShippingPlaceName || ''
                    setCoupangOutboundList(outCode ? [{ code: outCode, name: outName, address: '' }] : [])
                    const retCode = formData.returnCenterCode || ''
                    const retName = formData.returnCenterName || ''
                    const retAddr = formData.returnCenterAddress || ''
                    const retAddrDetail = formData.returnCenterAddressDetail || ''
                    const retZip = formData.returnCenterZipcode || ''
                    const retPhone = formData.returnCenterPhone || ''
                    setCoupangInboundList(retCode ? [{ code: retCode, name: retName, address: retAddr, address_detail: retAddrDetail, zipcode: retZip, phone: retPhone }] : [])
                  }
                }}
                style={{
                  padding: '0.15rem 0.4rem', borderRadius: '4px', fontSize: '0.7rem',
                  background: editingAccountId === a.id ? 'rgba(255,140,0,0.15)' : 'rgba(60,60,60,0.8)',
                  color: editingAccountId === a.id ? '#FF8C00' : '#C5C5C5',
                  border: editingAccountId === a.id ? '1px solid #FF8C00' : '1px solid #3D3D3D',
                  cursor: 'pointer', whiteSpace: 'nowrap',
                }}
              >{editingAccountId === a.id ? '수정중' : '수정'}</button>
              <button
                onClick={() => handleAccountDelete(a.id)}
                style={{
                  padding: '0.15rem 0.4rem', borderRadius: '4px', fontSize: '0.7rem',
                  background: 'rgba(255,80,80,0.15)', color: '#FF6B6B', border: '1px solid rgba(255,80,80,0.3)',
                  cursor: 'pointer', whiteSpace: 'nowrap',
                }}
              >삭제</button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
